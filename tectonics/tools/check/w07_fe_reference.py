"""Tiny independent W07 Q2/P1-discontinuous Stokes reference, NOT a backend.

Uniform rectangles, constant positive Newtonian viscosity, binary64, x-right /
z-up, and unit out-of-plane width. The weak form uses 2 eta D:D and -p div(v),
with physical outward traction on the RHS. No Atlas/MAC operator is imported.

The stable mixed element and weak form are described by May, Brown and Le
Pourhiet (2014), section II, https://jedbrown.org/files/MayBrownLePourhiet-pTatin3d-2014.pdf.
This is an independent 2D implementation, with our frozen W07 body-force sign.
Pressure is affine in physical coordinates on each axis-aligned rectangle;
using scaled local coordinates spans exactly that same P1 space here. This
implementation must not be reused unchanged on curved/deformed elements.

Boundary dictionaries contain all four sides and both Cartesian components:
{'left': {'u': ('velocity', callable_or_scalar), 'w': ('traction', value)}, ...}.
Callbacks take scalar (x,z). A traction is sigma*n, not a coordinate derivative.
Velocity traces are interpolated at Q2 boundary nodes. Pressure/gradient values
at element interfaces use the right/up trace (last element at outer boundaries).

Only a bounded sparse DIRECT solve is provided. Admission uses 64*N*N plus a
linear assembly allowance before allocating/factoring, capped at 128 MiB. It is
a conservative reference admission estimate, not an OS RSS or runtime bound.
Pure traction with unconstrained rigid modes refuses; no artificial pin/drag.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
import time
from types import MappingProxyType

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import splu


MAX_REFERENCE_BYTES = 128*1024**2
MAX_EVALUATION_POINTS = 65536
_SIDES = ('left', 'right', 'bottom', 'top')
_COMPONENTS = ('u', 'w')
_NORMAL = {'left': (-1., 0.), 'right': (1., 0.), 'bottom': (0., -1.), 'top': (0., 1.)}


class FEReferenceError(ValueError):
    """Unsupported or numerically unresolved small-reference request."""


def _number(value, label, *, positive=False):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.number)):
        raise FEReferenceError(label+' must be a finite real scalar')
    value = float(value)
    if not math.isfinite(value) or (positive and value <= 0):
        raise FEReferenceError(label+' is outside the finite supported range')
    return value


def _frozen(array):
    value = np.asarray(array, dtype=np.float64)
    if not np.isfinite(value).all():
        raise FEReferenceError('reference result is not finite')
    return np.frombuffer(value.tobytes(), dtype=np.float64).reshape(value.shape)


def _boundary_records(boundaries):
    if type(boundaries) is not dict or set(boundaries) != set(_SIDES):
        raise FEReferenceError('all four boundary sides must be explicitly declared')
    records = {}
    for side in _SIDES:
        entry = boundaries[side]
        if type(entry) is not dict or set(entry) != set(_COMPONENTS):
            raise FEReferenceError('each side needs exactly one condition for u and w')
        for component in _COMPONENTS:
            record = entry[component]
            if (type(record) is not tuple or len(record) != 2 or
                    record[0] not in ('velocity', 'traction')):
                raise FEReferenceError('each component is one velocity OR outward traction pair')
            if not callable(record[1]):
                _number(record[1], side+' '+component)
            records[side, component] = record
    return MappingProxyType(records)


def _value(value, x, z):
    return _number(value(float(x), float(z)) if callable(value) else value, 'boundary value')


def _shape(xi, zeta, dx, dz):
    """Tensor Q2 nodal basis, reference order bottom-to-top then left-to-right."""
    x = np.array([.5*xi*(xi-1), 1-xi*xi, .5*xi*(xi+1)])
    z = np.array([.5*zeta*(zeta-1), 1-zeta*zeta, .5*zeta*(zeta+1)])
    gx = np.array([xi-.5, -2*xi, xi+.5])*(2/dx)
    gz = np.array([zeta-.5, -2*zeta, zeta+.5])*(2/dz)
    return np.outer(z, x).ravel(), np.outer(z, gx).ravel(), np.outer(gz, x).ravel()


def _element_nodes(ex, ez, nx):
    return np.array([(2*ez+j)*(2*nx+1)+2*ex+i for j in range(3) for i in range(3)])


def tensor_quadrature(nx, nz, width, height, *, order=5):
    """Common physical quadrature helper, independent of a solved FE mesh."""
    if any(type(v) is not int or v < 1 for v in (nx, nz, order)) or order > 12:
        raise FEReferenceError('positive bounded quadrature grid/order required')
    if nx*nz*order*order > MAX_EVALUATION_POINTS:
        raise FEReferenceError('independent quadrature point budget exceeded')
    width = _number(width, 'width', positive=True)
    height = _number(height, 'height', positive=True)
    q, w = np.polynomial.legendre.leggauss(order)
    points, weights = [], []
    for ez in range(nz):
        for ex in range(nx):
            for j in range(order):
                for i in range(order):
                    points.append(((ex+(q[i]+1)/2)*width/nx, (ez+(q[j]+1)/2)*height/nz))
                    weights.append(w[i]*w[j]*width*height/(4*nx*nz))
    return _frozen(points), _frozen(weights)


@dataclass(frozen=True, slots=True)
class FEReferenceResult:
    nx: int
    nz: int
    width: float
    height: float
    eta: float
    pressure_mean: float | None
    velocity_coefficients: np.ndarray
    pressure_coefficients: np.ndarray
    boundary_reaction_forces: np.ndarray
    diagnostics: object
    operator_signature: str
    unknown_count: int
    solved_unknown_count: int
    projected_work_bytes: int
    setup_seconds: float
    factor_seconds: float
    load_seconds: float
    solve_seconds: float
    diagnostics_seconds: float
    max_work_bytes: int

    def evaluate(self, points):
        """Return u,w,p and (Dxx,Dzz,Dxz)/(sigma_xx,sigma_zz,sigma_xz).

        Velocity is continuous; pressure and strain have explicit element traces.
        Divergence here is the pointwise approximation error, distinct from the
        exactly assembled P1 weak-continuity residual reported in diagnostics.
        """
        points = np.asarray(points)
        if points.dtype.kind not in 'iuf' or points.ndim != 2 or points.shape[1] != 2:
            raise FEReferenceError('points must be a real (N,2) physical coordinate array')
        if (len(points) > MAX_EVALUATION_POINTS or
                self.projected_work_bytes+256*len(points) > self.max_work_bytes):
            raise FEReferenceError('reference evaluation work budget exceeded')
        points = np.asarray(points, dtype=np.float64)
        if (not np.isfinite(points).all() or np.any(points < 0) or
                np.any(points[:, 0] > self.width) or np.any(points[:, 1] > self.height)):
            raise FEReferenceError('evaluation points must remain inside the reference rectangle')
        u, w, p = np.empty(len(points)), np.empty(len(points)), np.empty(len(points))
        strain = np.empty((len(points), 3))
        dx, dz = self.width/self.nx, self.height/self.nz
        for row, (x, z) in enumerate(points):
            ex = min(self.nx-1, int(x/dx)); ez = min(self.nz-1, int(z/dz))
            xi, zeta = 2*(x/dx-ex)-1, 2*(z/dz-ez)-1
            shape, gx, gz = _shape(xi, zeta, dx, dz)
            nodes = _element_nodes(ex, ez, self.nx)
            uc, wc = self.velocity_coefficients[nodes].T
            u[row], w[row] = shape@uc, shape@wc
            p[row] = self.pressure_coefficients[ez, ex]@np.array([1., xi, zeta])
            strain[row] = gx@uc, gz@wc, .5*(gz@uc+gx@wc)
        stress = 2*self.eta*strain
        stress[:, :2] -= p[:, None]
        return {'u':_frozen(u), 'w':_frozen(w), 'p':_frozen(p), 'strain':_frozen(strain),
                'stress':_frozen(stress), 'divergence':_frozen(strain[:, 0]+strain[:, 1]),
                'sigma_yy':_frozen(-p)}


@dataclass(frozen=True, slots=True, init=False)
class PreparedFEReference:
    """Reusable topology/matrix/factor for pure RHS and boundary-value changes.

    Geometry, viscosity, component types and pressure policy are fixed by this
    immutable preparation. No automatic cache or production source binding is
    supplied: the parent benchmark owns its exact source/case identity.
    """
    nx: int
    nz: int
    width: float
    height: float
    eta: float
    pressure_mean: float | None
    velocity_scale: float
    unknown_count: int
    solved_unknown_count: int
    projected_work_bytes: int
    max_work_bytes: int
    operator_signature: str
    setup_seconds: float
    factor_seconds: float
    _records: object = field(repr=False, compare=False)
    _pattern: tuple = field(repr=False, compare=False)
    _coordinates: object = field(repr=False, compare=False)
    _fixed: object = field(repr=False, compare=False)
    _free: object = field(repr=False, compare=False)
    _operator: object = field(repr=False, compare=False)
    _stiffness: object = field(repr=False, compare=False)
    _divergence: object = field(repr=False, compare=False)
    _factor: object = field(repr=False, compare=False)
    _quadrature: object = field(repr=False, compare=False)
    _side_nodes: object = field(repr=False, compare=False)

    def __init__(self, nx, nz, width, height, eta, boundaries, *, pressure_mean=None,
                 max_work_bytes=MAX_REFERENCE_BYTES, velocity_scale=1.):
        started = time.perf_counter()
        if type(nx) is not int or type(nz) is not int or nx < 1 or nz < 1:
            raise FEReferenceError('positive integer element counts required')
        width, height, eta, velocity_scale = (_number(v, label, positive=True) for v, label in
            ((width, 'width'), (height, 'height'), (eta, 'viscosity'), (velocity_scale, 'velocity scale')))
        if type(max_work_bytes) is not int or not 1 <= max_work_bytes <= MAX_REFERENCE_BYTES:
            raise FEReferenceError('reference work allowance must be positive and at most 128 MiB')
        records = _boundary_records(boundaries)
        normal_fixed = all(records[side, 'u' if side in ('left','right') else 'w'][0] == 'velocity'
                           for side in _SIDES)
        if normal_fixed:
            if pressure_mean is None:
                raise FEReferenceError('all normal velocities fixed: an explicit mean-pressure gauge is required')
            pressure_mean = _number(pressure_mean, 'mean pressure')
        elif pressure_mean is not None:
            raise FEReferenceError('normal traction fixes pressure: an additional mean gauge is invalid')
        nnode = (2*nx+1)*(2*nz+1)
        nv, npres = 2*nnode, 3*nx*nz
        count = nv+npres+int(normal_fixed)
        work = 64*count*count+4096*count+8192*nx*nz+65536
        if work > max_work_bytes:
            raise FEReferenceError('direct FE reference fill/memory admission exceeds work budget')
        dx, dz = width/nx, height/nz
        if not all(math.isfinite(v) and v > 0 for v in (dx, dz, dx*dz, width*height)):
            raise FEReferenceError('reference geometry is not finite and resolvable')
        coordinates = np.array([(i*width/(2*nx), j*height/(2*nz))
                                for j in range(2*nz+1) for i in range(2*nx+1)])
        side_nodes = {'left':np.arange(0, nnode, 2*nx+1), 'right':np.arange(2*nx, nnode, 2*nx+1),
                      'bottom':np.arange(2*nx+1), 'top':np.arange(nnode-(2*nx+1), nnode)}
        fixed = sorted({int(node)+component*nnode for side in _SIDES for component, name in enumerate(_COMPONENTS)
                        if records[side, name][0] == 'velocity' for node in side_nodes[side]})
        # A missing translation/rotation mode is a physical underconstraint, not
        # something to discover via an arbitrary pressure pin or LU warning.
        rigid = []
        for dof in fixed:
            x, z = coordinates[dof % nnode]/max(width, height)
            rigid.append((1., 0., -z) if dof < nnode else (0., 1., x))
        if not rigid or np.linalg.matrix_rank(np.asarray(rigid)) < 3:
            raise FEReferenceError('Dirichlet constraints leave rigid modes; explicit rigid projection is unsupported here')
        q, qw = np.polynomial.legendre.leggauss(5)
        quadrature = []
        local_k, local_b = np.zeros((18,18)), np.zeros((3,18))
        for j, zeta in enumerate(q):
            for i, xi in enumerate(q):
                shape, gx, gz = _shape(xi, zeta, dx, dz)
                weight = qw[i]*qw[j]*dx*dz/4
                pshape = np.array([1., xi, zeta])
                local_k[:9,:9] += eta*weight*(2*np.outer(gx,gx)+np.outer(gz,gz))
                local_k[9:,9:] += eta*weight*(np.outer(gx,gx)+2*np.outer(gz,gz))
                local_k[:9,9:] += eta*weight*np.outer(gz,gx)
                local_k[9:,:9] += eta*weight*np.outer(gx,gz)
                local_b[:,:9] -= weight*np.outer(pshape,gx)
                local_b[:,9:] -= weight*np.outer(pshape,gz)
                quadrature.append((float(xi), float(zeta), float(weight), _frozen(shape)))
        kr, kc, kv, br, bc, bv = [], [], [], [], [], []
        for ez in range(nz):
            for ex in range(nx):
                nodes = _element_nodes(ex, ez, nx)
                velocity = np.r_[nodes, nodes+nnode]
                pressure = 3*(ez*nx+ex)+np.arange(3)
                kr.extend(np.repeat(velocity,18)); kc.extend(np.tile(velocity,18)); kv.extend(local_k.ravel())
                br.extend(np.repeat(pressure,18)); bc.extend(np.tile(velocity,3)); bv.extend(local_b.ravel())
        stiffness = sparse.coo_matrix((kv,(kr,kc)),shape=(nv,nv)).tocsr()
        divergence = sparse.coo_matrix((bv,(br,bc)),shape=(npres,nv)).tocsr()
        if normal_fixed:
            weights = np.zeros(npres); weights[::3] = dx*dz
            pressure_weight = sparse.csr_matrix(weights[:,None])
            operator = sparse.bmat([[stiffness, divergence.T, None],
                                   [divergence, None, pressure_weight],
                                   [None, pressure_weight.T, None]],format='csc')
        else:
            operator = sparse.bmat([[stiffness, divergence.T], [divergence, None]],format='csc')
        fixed = np.asarray(fixed, dtype=np.int64)
        free = np.setdiff1d(np.arange(count), fixed)
        pattern = tuple((side, component, records[side, component][0]) for side in _SIDES for component in _COMPONENTS)
        signature = hashlib.sha256(json.dumps(dict(method='w07-q2-p1-disc-reference-v1', nx=nx, nz=nz,
            width=width, height=height, eta=eta, pattern=pattern, pressure_mean=pressure_mean),
            sort_keys=True, separators=(',',':')).encode()).hexdigest()
        data = dict(nx=nx, nz=nz, width=width, height=height, eta=eta, pressure_mean=pressure_mean,
            velocity_scale=velocity_scale, unknown_count=count, solved_unknown_count=len(free),
            projected_work_bytes=work, max_work_bytes=max_work_bytes, operator_signature=signature,
            _records=records, _pattern=pattern, _coordinates=_frozen(coordinates), _fixed=fixed,
            _free=free, _operator=operator, _stiffness=stiffness, _divergence=divergence,
            _quadrature=tuple(quadrature), _side_nodes=MappingProxyType(side_nodes))
        for key, value in data.items():
            object.__setattr__(self,key,value)
        # Check corner traces and closed-box flux before factorisation as well.
        self._lift(records)
        setup_done = time.perf_counter()
        try:
            factor = splu(operator[free,:][:,free].tocsc())
        except RuntimeError as exc:
            raise FEReferenceError('reference matrix factorisation failed; no fallback or stabilisation') from exc
        object.__setattr__(self, '_factor', factor)
        object.__setattr__(self, 'setup_seconds', setup_done-started)
        object.__setattr__(self, 'factor_seconds', time.perf_counter()-setup_done)

    def _lift(self, records):
        nnode = len(self._coordinates)
        lift = np.zeros(self.unknown_count)
        assigned = {}
        for side in _SIDES:
            for component, name in enumerate(_COMPONENTS):
                if records[side,name][0] != 'velocity':
                    continue
                for node in self._side_nodes[side]:
                    value = _value(records[side,name][1], *self._coordinates[node])
                    dof = int(node)+component*nnode
                    if dof in assigned and abs(assigned[dof]-value) > 64*np.finfo(float).eps*max(1.,abs(value),abs(assigned[dof])):
                        raise FEReferenceError('conflicting prescribed velocity traces at a corner')
                    assigned[dof] = value
                    lift[dof] = value
        if self.pressure_mean is not None:
            flux, absolute = [], []
            for side in _SIDES:
                normal = _NORMAL[side]
                component = 0 if side in ('left','right') else 1
                nodes = self._side_nodes[side]
                spacing = (self.height/self.nz if component == 0 else self.width/self.nx)
                for first in range(0,len(nodes)-2,2):
                    values = lift[nodes[first:first+3]+component*nnode]
                    weighted = spacing*float(values@np.array([1.,4.,1.]))/6
                    flux.append(normal[component]*weighted)
                    absolute.append(spacing*float(abs(values)@np.array([1.,4.,1.]))/6)
            scale = max(self.velocity_scale*(self.width+self.height), math.fsum(absolute))
            if abs(math.fsum(flux)) > 1e-12*scale:
                raise FEReferenceError('prescribed outward boundary flux is incompatible with incompressibility')
        return lift

    def solve(self, body_force, *, boundaries=None):
        """Reuse exact factors for a new body load or compatible boundary values."""
        if not callable(body_force):
            raise FEReferenceError('body force must be a callable returning (fx,fz)')
        started = time.perf_counter()
        records = self._records if boundaries is None else _boundary_records(boundaries)
        if tuple((side, component, records[side,component][0]) for side in _SIDES for component in _COMPONENTS) != self._pattern:
            raise FEReferenceError('boundary component types changed; prepare a new reference operator')
        lift = self._lift(records)
        nnode = len(self._coordinates); nv=2*nnode
        body, traction = np.zeros(nv), np.zeros(nv)
        dx,dz = self.width/self.nx,self.height/self.nz
        for ez in range(self.nz):
            for ex in range(self.nx):
                nodes = _element_nodes(ex,ez,self.nx)
                for xi,zeta,weight,shape in self._quadrature:
                    x,z=(ex+(xi+1)/2)*dx,(ez+(zeta+1)/2)*dz
                    force=np.asarray(body_force(float(x),float(z)))
                    if force.shape != (2,) or force.dtype.kind not in 'iuf' or not np.isfinite(force).all():
                        raise FEReferenceError('body force must return two finite real components')
                    body[nodes] += weight*shape*force[0]
                    body[nodes+nnode] += weight*shape*force[1]
        q,qw=np.polynomial.legendre.leggauss(5)
        for side in _SIDES:
            vertical = side in ('left','right')
            segments = self.nz if vertical else self.nx
            for segment in range(segments):
                ex = (0 if side=='left' else self.nx-1) if vertical else segment
                ez = segment if vertical else (0 if side=='bottom' else self.nz-1)
                nodes = _element_nodes(ex,ez,self.nx)
                for s,weight in zip(q,qw):
                    xi = (-1. if side=='left' else 1.) if vertical else s
                    zeta = s if vertical else (-1. if side=='bottom' else 1.)
                    shape,_,_ = _shape(xi,zeta,dx,dz)
                    x,z=(ex+(xi+1)/2)*dx,(ez+(zeta+1)/2)*dz
                    weight *= (dz if vertical else dx)/2
                    for component,name in enumerate(_COMPONENTS):
                        if records[side,name][0]=='traction':
                            value=_value(records[side,name][1],x,z)
                            traction[nodes+component*nnode] += weight*shape*value
        rhs=np.zeros(self.unknown_count); rhs[:nv]=body+traction
        if self.pressure_mean is not None:
            rhs[-1]=self.pressure_mean*self.width*self.height
        reduced=(rhs-self._operator@lift)[self._free]
        load_done=time.perf_counter()
        solution=lift.copy(); solution[self._free]=self._factor.solve(reduced)
        solve_done=time.perf_counter()
        if not np.isfinite(solution).all():
            raise FEReferenceError('nonfinite reference solution')
        residual=self._operator@solution-rhs
        algebraic_scale=max(float(np.max(abs(rhs))),self.eta*self.velocity_scale,np.finfo(float).tiny)
        if np.max(abs(residual[self._free]))/algebraic_scale > 1e-12:
            raise FEReferenceError('reference true algebraic residual failed; no inaccurate fallback')
        velocity=solution[:nv]
        pressure=solution[nv:nv+3*self.nx*self.nz].reshape(self.nz,self.nx,3)
        reactions=np.zeros(nv); reactions[self._fixed]=residual[self._fixed]
        divergence=self._divergence@velocity
        mean_pressure=float(np.mean(pressure[:,:,0]))
        dissipation=float(velocity@(self._stiffness@velocity))
        body_work=float(velocity@body); applied_work=float(velocity@traction)
        reaction_work=float(velocity@reactions)
        total=body+traction+reactions
        force=(float(math.fsum(total[:nnode])),float(math.fsum(total[nnode:])))
        torque=float(math.fsum(self._coordinates[:,0]*total[nnode:]-self._coordinates[:,1]*total[:nnode]))
        free_velocity=self._free[self._free<nv]
        work_residual=dissipation-body_work-applied_work-reaction_work
        diagnostics=MappingProxyType(dict(momentum_residual_max=float(np.max(abs(residual[free_velocity]),initial=0.)),
            weak_continuity_moment_max=float(np.max(abs(divergence))),
            weak_continuity_scaled_max=float(np.max(abs(divergence)))/(self.velocity_scale*max(self.width,self.height)),
            integrated_boundary_flux=float(-math.fsum(divergence[::3])),
            maximum_element_flux=float(np.max(abs(divergence[::3]))), mean_pressure=mean_pressure,
            gauge_error=None if self.pressure_mean is None else mean_pressure-self.pressure_mean,
            gauge_multiplier=None if self.pressure_mean is None else float(solution[-1]),
            dissipation=dissipation, body_work=body_work, applied_traction_work=applied_work,
            dirichlet_reaction_work=reaction_work, work_residual=work_residual,
            scaled_work_residual=abs(work_residual)/max(self.eta*self.velocity_scale**2,abs(dissipation),
                abs(body_work)+abs(applied_work)+abs(reaction_work)),
            net_force=force, net_torque=torque,
            pressure_kind='mean-gauged' if self.pressure_mean is not None else 'traction-fixed'))
        return FEReferenceResult(self.nx,self.nz,self.width,self.height,self.eta,self.pressure_mean,
            _frozen(np.column_stack((velocity[:nnode],velocity[nnode:]))), _frozen(pressure),
            _frozen(np.column_stack((reactions[:nnode],reactions[nnode:]))), diagnostics,
            self.operator_signature,self.unknown_count,self.solved_unknown_count,self.projected_work_bytes,
            self.setup_seconds,self.factor_seconds,load_done-started,solve_done-load_done,
            time.perf_counter()-solve_done,self.max_work_bytes)


def prepare_reference(nx,nz,width,height,eta,boundaries,**options):
    return PreparedFEReference(nx,nz,width,height,eta,boundaries,**options)


def solve_reference(nx,nz,width,height,eta,body_force,boundaries,**options):
    return prepare_reference(nx,nz,width,height,eta,boundaries,**options).solve(body_force)
