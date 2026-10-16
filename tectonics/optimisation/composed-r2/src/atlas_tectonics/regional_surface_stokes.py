"""W07 mapped Q2/physical-P1-discontinuous regional surface mechanics.

SPDX-License-Identifier: AGPL-3.0-only
This explicitly adopts the finite-element route for curved geometry. The MAC
operator and the small rectangular FE comparator are unchanged. Mesh x is affine
and fixed; z is a continuous Q2 graph mapping with an exactly checked positive
vertical Jacobian everywhere. Pressure uses physical affine coordinates, as in
May, Brown & Le Pourhiet (2014), section II: https://jedbrown.org/files/MayBrownLePourhiet-pTatin3d-2014.pdf.
The full 2 eta D:D weak operator, current mapped derivatives, body-force sign
div(sigma)+f=0 and physical traction sigma*n are assembled on that geometry.

Default boundaries: bottom no slip, vertical sides normal velocity zero and
tangential traction zero, top physical pressure plus tangential traction. Top
normal traction determines absolute pressure; there is no pressure gauge row.
Continuity is elementwise weak P1 continuity, not pointwise zero divergence.
Laplacian mesh extension follows ASPECT's ALE method with the explicitly chosen
vertical graph motion, fixed x, fixed bottom and natural vertical side motion.
The caller owns the weak surface kinematic projection and time integration.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import math
import threading
from time import perf_counter

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import LinearOperator, gmres, spilu, splu

from ._validation import TectonicsError, scalar, input_shape, read_array, frozen
from .constitutive import _cancel
from .resources import WorkBudget, select_budget
from .stokes_execution import _native_lease


def _q2(x):
    x = np.asarray(x)
    return (np.stack((.5*x*(x-1), 1-x*x, .5*x*(x+1)), axis=-1),
            np.stack((x-.5, -2*x, x+.5), axis=-1))


def _basis(xi, zeta):
    x, dx = _q2(xi); z, dz = _q2(zeta)
    return ((z[..., :, None]*x[..., None, :]).reshape(*np.shape(xi), 9),
            (z[..., :, None]*dx[..., None, :]).reshape(*np.shape(xi), 9),
            (dz[..., :, None]*x[..., None, :]).reshape(*np.shape(xi), 9))


def _values(value, points, shape, label, *, components=0):
    if callable(value):
        value = value(points[..., 0], points[..., 1])
    actual = input_shape(value, label)
    permitted = ((), shape) if not components else ((components,), shape+(components,))
    if actual not in permitted:
        raise TectonicsError(label+' has incompatible physical quadrature support')
    array = read_array(value, label)
    return np.broadcast_to(array, shape if not components else shape+(components,))


def _csr(local, rows, cols, shape):
    nr, nc = local.shape[-2:]
    return sparse.coo_matrix((local.ravel(),
        (np.broadcast_to(rows[:, :, None], (len(rows), nr, nc)).ravel(),
         np.broadcast_to(cols[:, None, :], (len(cols), nr, nc)).ravel())), shape=shape).tocsr()


class PreparedSurfaceStokes2D:
    """Prepared reference quadrature/topology; one bounded latest metric cache.

    Counts are elements, 1..64 per axis. Quadrature order is explicitly 4 or 5.
    Both solvers use the same current matrix. Direct admission is 64*N**2 plus
    assembly; GMRES uses fixed ILU(8) velocity and inverse-viscosity pressure-mass
    block preconditioning, restart 60, at most 1200 iterations, true rtol 1e-12.
    No hidden switch to direct or a different grid occurs after refusal/failure.
    """
    def __init__(self, nx, nz, *, quadrature_order=5, method='gmres', budget=None,
                 length_scale_m=1., velocity_scale_m_s=1., viscosity_scale_pa_s=1.):
        if any(type(n) is not int or not 1 <= n <= 64 for n in (nx, nz)):
            raise TectonicsError('mapped W07 supports 1..64 elements per axis')
        if quadrature_order not in (4, 5) or type(quadrature_order) is not int:
            raise TectonicsError('explicit Gauss quadrature order 4 or 5 required')
        if method not in ('direct', 'gmres'):
            raise TectonicsError('explicit direct or gmres method required')
        self.nx, self.nz, self.order, self.method = nx, nz, quadrature_order, method
        self.length_scale = scalar(length_scale_m, 'length scale', positive=True)
        self.velocity_scale = scalar(velocity_scale_m_s, 'velocity scale', positive=True)
        self.viscosity_scale = scalar(viscosity_scale_pa_s, 'viscosity scale', positive=True)
        self.elements, self.nnode = nx*nz, (2*nx+1)*(2*nz+1)
        self.unknowns = 2*self.nnode+3*self.elements
        self.budget = WorkBudget(128*1024**2, parent=select_budget(budget))
        self.work_bytes = 38000*self.elements+4096*self.unknowns+1024**2
        if method == 'direct':
            self.work_bytes += 64*self.unknowns**2
        self.metric_bytes = (400+320*quadrature_order**2)*self.elements+64*self.nnode+4096
        self._owner, self._active, self._closed = threading.get_ident(), False, False
        self._geometry = self._geometry_id = self._metric_guard = None
        self._laplacian_diagnostics = None
        self._topology_guard = self.budget.reserve(1024*self.elements+32768, category='surface-fe-topology')
        self._topology_guard.__enter__()
        try:
            with self.budget.reserve(self.work_bytes+self.metric_bytes, category='surface-fe-admission'):
                pass
            q, qw = np.polynomial.legendre.leggauss(quadrature_order)
            xi, ze = np.meshgrid(q, q)
            self._shape, self._dxi, self._dze = _basis(xi.ravel(), ze.ravel())
            self._q, self._qw = q, qw
            self._weight = (qw[:, None]*qw[None, :]).ravel()
            self._conn = np.asarray([[(2*ez+j)*(2*nx+1)+2*ex+i for j in range(3) for i in range(3)]
                                     for ez in range(nz) for ex in range(nx)], dtype=np.int64)
            self._vconn = np.concatenate((self._conn, self._conn+self.nnode), axis=1)
            self._pconn = np.arange(3*self.elements).reshape(self.elements, 3)
            self._sides = dict(bottom=np.arange(2*nx+1),
                top=np.arange(2*nz*(2*nx+1), self.nnode),
                left=np.arange(0, self.nnode, 2*nx+1), right=np.arange(2*nx, self.nnode, 2*nx+1))
            self._fixed = np.unique(np.r_[self._sides['bottom'], self._sides['bottom']+self.nnode,
                                          self._sides['left'], self._sides['right']])
            self._freev = np.setdiff1d(np.arange(2*self.nnode), self._fixed)
        except BaseException:
            self._closed = True
            self._topology_guard.__exit__(None, None, None)
            raise

    @contextmanager
    def _operation(self, cancel):
        if self._closed or self._active or threading.get_ident() != self._owner:
            raise TectonicsError('surface plan closed/active or wrong driving thread')
        self._active = True
        try:
            _cancel(cancel)
            with _native_lease():
                yield
            _cancel(cancel)
        finally:
            self._active = False

    def close(self):
        if self._closed:
            return
        if self._active or threading.get_ident() != self._owner:
            raise TectonicsError('close surface plan on its idle driving thread')
        self._geometry = None
        if self._metric_guard is not None:
            self._metric_guard.__exit__(None, None, None)
            self._metric_guard = None
        self._topology_guard.__exit__(None, None, None)
        self._closed = True

    def __enter__(self):
        if self._closed:
            raise TectonicsError('surface plan is closed')
        return self

    def __exit__(self, *_):
        self.close()

    def _metrics(self, mesh):
        if input_shape(mesh, 'mesh') != (2*self.nz+1, 2*self.nx+1, 2):
            raise TectonicsError('physical Q2 mesh needs shape (2*nz+1,2*nx+1,2)')
        mesh = frozen(read_array(mesh, 'mesh'))
        key = hashlib.sha256(mesh.tobytes()).hexdigest()
        if key == self._geometry_id:
            return self._geometry
        if self._metric_guard is not None:
            self._geometry = self._geometry_id = None
            self._metric_guard.__exit__(None, None, None)
            self._metric_guard = None
        guard = self.budget.reserve(self.metric_bytes, category='surface-fe-metrics')
        guard.__enter__()
        try:
            width = float(mesh[0, -1, 0]-mesh[0, 0, 0])
            if width <= 0. or not math.isfinite(width):
                raise TectonicsError('positive physical width required')
            wanted = mesh[0, 0, 0]+np.arange(2*self.nx+1)*(width/(2*self.nx))
            if np.max(np.abs(mesh[..., 0]-wanted[None, :])) > 1e-12*width:
                raise TectonicsError('surface backend requires affine fixed x columns; no horizontal distortion')
            if np.max(np.abs(mesh[0, :, 1])) > 1e-12*max(width, self.length_scale):
                raise TectonicsError('surface backend requires a fixed flat bottom z=0')
            xyz = mesh.reshape(self.nnode, 2)[self._conn]
            # Since x is affine, detJ=(dx/dxi)*(dz/dzeta). The latter is linear
            # in zeta and quadratic in xi. Check exact minima, including between
            # Gauss points: zeta endpoints and xi endpoints/quadratic stationary
            # points. Positive samples at Gauss points alone are insufficient.
            minimum = math.inf
            for ze in (-1., 1.):
                _, _, derivative = _basis(np.asarray([-1., 0., 1.]), np.full(3, ze))
                values = np.einsum('qi,ei->eq', derivative, xyz[..., 1])
                a = .5*(values[:, 0]+values[:, 2])-values[:, 1]
                b = .5*(values[:, 2]-values[:, 0])
                c = values[:, 1]
                minimum = min(minimum, float(values.min()))
                active = a > 0.
                vertex = np.zeros(self.elements)
                np.divide(-b, 2*a, out=vertex, where=active)
                active &= np.abs(vertex) < 1.
                if np.any(active):
                    minimum = min(minimum, float((a*vertex**2+b*vertex+c)[active].min()))
            characteristic = max(float(np.max(mesh[..., 1])), self.length_scale)/self.nz
            if not math.isfinite(minimum) or minimum <= 64*np.finfo(float).eps*characteristic:
                raise TectonicsError('nonpositive or unresolved Q2 Jacobian between/beyond quadrature points')
            point = np.einsum('qi,eip->eqp', self._shape, xyz)
            zx = np.einsum('qi,ei->eq', self._dxi, xyz[..., 1])
            zz = np.einsum('qi,ei->eq', self._dze, xyz[..., 1])
            xx = width/(2*self.nx)
            gx = (self._dxi[None]-self._dze[None]*(zx/zz)[..., None])/xx
            gz = self._dze[None]/zz[..., None]
            weight = xx*zz*self._weight
            centre = xyz[:, 4]
            scales = np.column_stack((np.full(self.elements, xx), .5*(xyz[:, 7, 1]-xyz[:, 1, 1])))
            pshape = np.concatenate((np.ones((self.elements, self.order**2, 1)),
                                     (point-centre[:, None, :])/scales[:, None, :]), axis=2)
            result = dict(mesh=mesh, xyz=xyz, points=point, gx=gx, gz=gz, weight=weight,
                          pressure_basis=pshape, pressure_origin=centre, pressure_scale=scales,
                          minimum_jacobian=minimum*xx, volume=np.sum(weight, axis=1))
            if not all(np.isfinite(result[name]).all() for name in ('gx','gz','weight','pressure_basis')):
                raise TectonicsError('mapped geometry outside finite binary64 range')
            self._geometry, self._geometry_id, self._metric_guard = result, key, guard
            return result
        except BaseException:
            guard.__exit__(None, None, None)
            raise

    def _edge(self, geometry, side):
        vertical = side in ('left', 'right')
        count = self.nz if vertical else self.nx
        elements = (np.arange(self.nz)*self.nx+(0 if side == 'left' else self.nx-1) if vertical else
                    np.arange(self.nx)+(0 if side == 'bottom' else (self.nz-1)*self.nx))
        xi = np.full(self.order, -1. if side == 'left' else 1.) if vertical else self._q
        ze = self._q if vertical else np.full(self.order, -1. if side == 'bottom' else 1.)
        shape, dxi, dze = _basis(xi, ze)
        xyz = geometry['xyz'][elements]
        points = np.einsum('qi,eip->eqp', shape, xyz)
        tangent = np.einsum('qi,eip->eqp', dze if vertical else dxi, xyz)
        length = np.linalg.norm(tangent, axis=-1)
        normal = (np.stack((-tangent[..., 1], tangent[..., 0]), axis=-1) if not vertical else
                  np.stack((tangent[..., 1], -tangent[..., 0]), axis=-1))
        if side in ('left', 'bottom'):
            normal = -normal
        normal /= length[..., None]
        return dict(elements=elements, shape=shape, points=points, tangent=tangent,
                    normal=normal, weight=length*self._qw, count=count)

    def validate_geometry(self, mesh_nodes_m, *, cancel=None):
        """Initial-state metric/Jacobian admission, with no mechanics factor/solve."""
        with self._operation(cancel):
            geometry=self._metrics(mesh_nodes_m)
            return dict(geometry_id=self._geometry_id,minimum_jacobian_m2=geometry['minimum_jacobian'],
                        element_volume_m2=frozen(geometry['volume'].reshape(self.nz,self.nx)),
                        domain_area_m2=math.fsum(geometry['volume']),quadrature_order=self.order)

    def _lift(self, geometry, prescribed):
        if prescribed is None:
            prescribed = {}
        if not isinstance(prescribed, dict) or not set(prescribed).issubset({'bottom','left_u','right_u'}):
            raise TectonicsError('prescribed traces may contain bottom, left_u and right_u only')
        lift = np.zeros(2*self.nnode)
        nodes = self._sides['bottom']; points = geometry['mesh'].reshape(-1, 2)[nodes]
        bottom = _values(prescribed.get('bottom', (0., 0.)), points, (len(nodes),), 'bottom velocity', components=2)
        lift[nodes], lift[nodes+self.nnode] = bottom[:, 0], bottom[:, 1]
        for side in ('left', 'right'):
            nodes = self._sides[side]; points = geometry['mesh'].reshape(-1, 2)[nodes]
            values = _values(prescribed.get(side+'_u', 0.), points, (len(nodes),), side+' normal velocity')
            if abs(values[0]-lift[nodes[0]]) > 1e-12*max(self.velocity_scale,abs(values[0])):
                raise TectonicsError('conflicting bottom/side corner velocity')
            lift[nodes] = values
        return lift

    def _velocity_inverse(self, matrix):
        diagonal = matrix.diagonal()
        if np.any(diagonal <= 0.):
            raise TectonicsError('nonpositive velocity block diagonal')
        scaling = 1/np.sqrt(diagonal)
        scaled = sparse.diags(scaling)@matrix@sparse.diags(scaling)
        factor = spilu(scaled.tocsc(), drop_tol=1e-7, fill_factor=8.)
        return lambda rhs: scaling*factor.solve(scaling*rhs)

    @staticmethod
    def _gmres(matrix, rhs, preconditioner, cancel):
        count = 0
        def callback(_):
            nonlocal count
            count += 1
            _cancel(cancel)
        if not np.any(rhs):
            return np.zeros_like(rhs), 0, 0.
        solution, info = gmres(matrix, rhs, M=preconditioner, rtol=1e-12, atol=0.,
                               restart=60, maxiter=1200, callback=callback, callback_type='legacy')
        true = float(np.linalg.norm(matrix@solution-rhs))/float(np.linalg.norm(rhs))
        if info != 0 or not math.isfinite(true) or true > 1e-12:
            raise TectonicsError(f'mapped GMRES convergence failed: info={info}, iterations={count}, true={true}')
        return solution, count, true

    def solve(self, mesh_nodes_m, viscosity_pa_s, body_force_n_m3, *, top_pressure_pa=0.,
              top_shear_traction_pa=0., boundary_velocity_m_s=None,
              side_shear_traction_pa=None, cancel=None):
        """Solve one physical snapshot; callbacks receive physical (x,z) arrays.

        Volume eta/force arrays use (nz,nx,nq,nq)[,+2]; top data (nx,nq).
        Positive top shear follows the left-to-right physical surface tangent.
        Optional left/right side shear values are signed physical +z traction;
        both default to zero. Nonzero values support independent Couette tests.
        Returns physical coefficients/quadrature fields, metrics and weak gates.
        """
        started = perf_counter()
        with self._operation(cancel):
            g = self._metrics(mesh_nodes_m)
            with self.budget.reserve(self.work_bytes, category='surface-fe-solve'):
                shape = (self.nz,self.nx,self.order,self.order)
                points = g['points'].reshape(shape+(2,))
                eta = _values(viscosity_pa_s, points, shape, 'quadrature viscosity').reshape(self.elements,-1)
                if np.any(eta <= 0.):
                    raise TectonicsError('positive current quadrature viscosity required')
                force = _values(body_force_n_m3, points, shape, 'physical body force', components=2).reshape(self.elements,-1,2)
                gx,gz,weight,P = g['gx'],g['gz'],g['weight'],g['pressure_basis']
                weighted = eta*weight
                xx = np.einsum('eq,eqi,eqj->eij',weighted,gx,gx)
                zz = np.einsum('eq,eqi,eqj->eij',weighted,gz,gz)
                xz = np.einsum('eq,eqi,eqj->eij',weighted,gx,gz)
                localK = np.empty((self.elements,18,18))
                localK[:,:9,:9],localK[:,9:,9:] = 2*xx+zz,xx+2*zz
                localK[:,:9,9:],localK[:,9:,:9] = xz.transpose(0,2,1),xz
                localB = -np.concatenate((np.einsum('eq,eqi,eqj->eij',weight,P,gx),
                                           np.einsum('eq,eqi,eqj->eij',weight,P,gz)),axis=2)
                K = _csr(localK,self._vconn,self._vconn,(2*self.nnode,2*self.nnode))
                B = _csr(localB,self._pconn,self._vconn,(3*self.elements,2*self.nnode))
                localbody = np.einsum('eq,qi,eqc->eic',weight,self._shape,force)
                body = np.zeros(2*self.nnode); traction = np.zeros_like(body)
                np.add.at(body,self._conn.ravel(),localbody[...,0].ravel())
                np.add.at(body,self._conn.ravel()+self.nnode,localbody[...,1].ravel())
                top = self._edge(g,'top')
                pressure = _values(top_pressure_pa,top['points'],(self.nx,self.order),'top external pressure')
                shear = _values(top_shear_traction_pa,top['points'],(self.nx,self.order),'top shear traction')
                tangent = top['tangent']/np.linalg.norm(top['tangent'],axis=-1)[...,None]
                load = -pressure[...,None]*top['normal']+shear[...,None]*tangent
                edge_loads={'top':load}
                localtop = np.einsum('eq,qi,eqc->eic',top['weight'],top['shape'],load)
                nodes = self._conn[top['elements']]
                np.add.at(traction,nodes.ravel(),localtop[...,0].ravel())
                np.add.at(traction,nodes.ravel()+self.nnode,localtop[...,1].ravel())
                sides={} if side_shear_traction_pa is None else side_shear_traction_pa
                if not isinstance(sides,dict) or not set(sides).issubset({'left','right'}):
                    raise TectonicsError('side shear traction accepts left/right signed z components')
                for side,value in sides.items():
                    edge=self._edge(g,side)
                    shear=_values(value,edge['points'],(self.nz,self.order),side+' shear traction')
                    edge_loads[side]=np.stack((np.zeros_like(shear),shear),axis=-1)
                    local_side=np.einsum('eq,qi,eq->ei',edge['weight'],edge['shape'],shear)
                    np.add.at(traction,self._conn[edge['elements']].ravel()+self.nnode,local_side.ravel())
                physical_lift = self._lift(g,boundary_velocity_m_s)
                L,U,E = self.length_scale,self.velocity_scale,self.viscosity_scale
                A = K[self._freev,:][:,self._freev]/E
                D = B[:,self._freev]/L
                rhs = np.r_[(body+traction-K@physical_lift)[self._freev]/(E*U),
                             -(B@physical_lift)/(U*L)]
                operator = sparse.bmat(((A,D.T),(D,None)),format='csr')
                assembled = perf_counter()
                if self.method == 'direct':
                    factor = splu(operator.tocsc()); prepared = perf_counter()
                    solution = factor.solve(rhs); iterations = 1
                    residual = np.linalg.norm(operator@solution-rhs)
                    true = float(residual/max(float(np.linalg.norm(rhs)),np.finfo(float).tiny))
                    if true > 1e-12:
                        raise TectonicsError('mapped direct true algebraic residual exceeds 1e-12')
                else:
                    ainv = self._velocity_inverse(A)
                    mass = np.einsum('eq,eqi,eqj->eij',weight*(E/eta)/(L*L),P,P)
                    minv = np.linalg.inv(mass)
                    nfree = len(self._freev)
                    def apply(r):
                        vu = ainv(r[:nfree])
                        vp = -np.einsum('eij,ej->ei',minv,(r[nfree:]-D@vu).reshape(-1,3)).ravel()
                        return np.r_[vu-ainv(D.T@vp),vp]
                    preconditioner = LinearOperator(operator.shape,matvec=apply,dtype=float)
                    prepared = perf_counter()
                    solution,iterations,true = self._gmres(operator,rhs,preconditioner,cancel)
                solved = perf_counter(); _cancel(cancel)
                velocity = physical_lift.copy(); velocity[self._freev] += U*solution[:len(self._freev)]
                pc = (E*U/L)*solution[len(self._freev):].reshape(self.elements,3)
                residual = K@velocity+B.T@pc.ravel()-body-traction
                reaction = np.zeros_like(velocity); reaction[self._fixed] = residual[self._fixed]
                weak = B@velocity
                dissipation = float(velocity@(K@velocity)); bodywork=float(velocity@body)
                tractionwork=float(velocity@traction); reactionwork=float(velocity@reaction)
                work = math.fsum((dissipation,-bodywork,-tractionwork,-reactionwork))
                force_scale = max(E*U,float(np.max(np.abs(body+traction))),np.finfo(float).tiny)
                momentum = float(np.max(np.abs(residual[self._freev])))/force_scale
                divergence = float(np.max(np.abs(weak)))/(U*L)
                work_relative = abs(work)/max(E*U*U,abs(dissipation),abs(bodywork)+abs(tractionwork)+abs(reactionwork))
                nodal = np.column_stack((velocity[:self.nnode],velocity[self.nnode:]))
                local = nodal[self._conn]
                velocity_q = np.einsum('qi,eic->eqc',self._shape,local)
                dux=np.einsum('eqi,ei->eq',gx,local[...,0]); dwz=np.einsum('eqi,ei->eq',gz,local[...,1])
                shear_rate=.5*(np.einsum('eqi,ei->eq',gz,local[...,0])+np.einsum('eqi,ei->eq',gx,local[...,1]))
                strain=np.stack((dux,dwz,shear_rate),axis=-1)
                pquad=np.einsum('eqi,ei->eq',P,pc)
                stress=2*eta[...,None]*strain; stress[...,:2]-=pquad[...,None]
                fluxes={}; quadrature_traction_work=0.
                for side in ('left','right','bottom','top'):
                    edge=self._edge(g,side)
                    trace=np.einsum('qi,eic->eqc',edge['shape'],local[edge['elements']])
                    fluxes[side]=float(np.sum(edge['weight']*np.sum(trace*edge['normal'],axis=-1)))
                    if side in edge_loads:
                        quadrature_traction_work+=float(np.sum(edge['weight']*np.sum(trace*edge_loads[side],axis=-1)))
                # Independently integrate the PUBLISHED physical strain/stress;
                # these checks do not multiply the assembled K or B matrices.
                # sigma:grad(v)=2 eta D:D-p div(v): pressure work is explicit,
                # rather than assuming the finite weak residual is exactly zero.
                qforce_u=np.einsum('eq,eqi,eq->ei',weight,gx,stress[...,0])+np.einsum('eq,eqi,eq->ei',weight,gz,stress[...,2])
                qforce_w=np.einsum('eq,eqi,eq->ei',weight,gz,stress[...,1])+np.einsum('eq,eqi,eq->ei',weight,gx,stress[...,2])
                internal=np.zeros(2*self.nnode)
                np.add.at(internal,self._conn.ravel(),qforce_u.ravel())
                np.add.at(internal,self._conn.ravel()+self.nnode,qforce_w.ravel())
                qresidual=internal-body-traction
                qcontinuity=np.einsum('eq,eqi,eq->ei',weight,P,strain[...,0]+strain[...,1])
                qreaction=np.zeros_like(velocity);qreaction[self._fixed]=qresidual[self._fixed]
                qdissipation=float(np.sum(2*eta*weight*(strain[...,0]**2+strain[...,1]**2+2*strain[...,2]**2)))
                qpressure_work=float(np.sum(weight*pquad*(strain[...,0]+strain[...,1])))
                qbody_work=float(np.sum(weight*np.sum(velocity_q*force,axis=-1)))
                qreaction_work=float(velocity@qreaction)
                qwork=math.fsum((qdissipation,-qpressure_work,-qbody_work,-quadrature_traction_work,-qreaction_work))
                qmomentum=float(np.max(np.abs(qresidual[self._freev])))/force_scale
                qdivergence=float(np.max(np.abs(qcontinuity)))/(U*L)
                qwork_scale=max(E*U*U,abs(qdissipation),abs(qpressure_work)+abs(qbody_work)+
                                abs(quadrature_traction_work)+abs(qreaction_work))
                qwork_relative=abs(qwork)/qwork_scale
                flux=math.fsum(fluxes.values())
                volume_flux=qcontinuity[:,0]
                flux_identity=abs(flux-math.fsum(volume_flux))/(U*L)
                volume_flux_relative=abs(flux)/(U*L)
                gates=(momentum<=1e-9 and divergence<=1e-10 and work_relative<=1e-9 and
                       true<=1e-12 and flux_identity<=1e-10 and volume_flux_relative<=1e-10 and
                       qmomentum<=1e-9 and qdivergence<=1e-10 and qwork_relative<=1e-9)
                diagnostics=dict(gates_passed=gates,momentum_residual=qmomentum,
                    weak_continuity_scaled_max=qdivergence,normalised_work_residual=qwork_relative,
                    linear_residual=true,momentum_residual_n_per_m=float(np.max(np.abs(qresidual[self._freev]))),
                    weak_continuity_moment_max_m2_s=float(np.max(np.abs(qcontinuity))),
                    pointwise_divergence_max_s_1=float(np.max(np.abs(dux+dwz))),
                    integrated_boundary_flux_m2_s=flux,boundary_flux_m2_s=fluxes,
                    global_volume_flux_relative=volume_flux_relative,
                    flux_divergence_identity_relative=flux_identity,dissipation_w_per_m=qdissipation,
                    body_work_w_per_m=qbody_work,traction_work_w_per_m=quadrature_traction_work,
                    reaction_work_w_per_m=qreaction_work,pressure_work_w_per_m=qpressure_work,
                    work_residual_w_per_m=qwork,
                    algebraic_momentum_residual=momentum,algebraic_weak_continuity_scaled_max=divergence,
                    algebraic_dissipation_w_per_m=dissipation,algebraic_work_residual_w_per_m=work,
                    quadrature_scatter_difference_n_per_m=float(np.max(np.abs(qresidual-residual))),
                    quadrature_continuity_difference_m2_s=float(np.max(np.abs(qcontinuity+weak.reshape(self.elements,3)))),
                    physical_pressure='top-traction-determined; no gauge removal',iterations=iterations,
                    minimum_jacobian_m2=g['minimum_jacobian'],quadrature_order=self.order)
                if not gates:
                    raise TectonicsError('mapped returned-field mechanics gates failed: '+str(diagnostics))
                result=dict(mesh_nodes_m=g['mesh'],velocity_nodes_m_s=frozen(nodal.reshape(2*self.nz+1,2*self.nx+1,2)),
                    pressure_coefficients_pa=frozen(pc.reshape(self.nz,self.nx,3)),
                    pressure_origin_m=frozen(g['pressure_origin'].reshape(self.nz,self.nx,2)),
                    pressure_scale_m=frozen(g['pressure_scale'].reshape(self.nz,self.nx,2)),
                    quadrature_points_m=frozen(points),quadrature_weights_m2=frozen(weight.reshape(shape)),
                    pressure_q_pa=frozen(pquad.reshape(shape)),velocity_q_m_s=frozen(velocity_q.reshape(shape+(2,))),
                    strain_q_s_1=frozen(strain.reshape(shape+(3,))),stress_q_pa=frozen(stress.reshape(shape+(3,))),
                    viscosity_q_pa_s=frozen(eta.reshape(shape)),
                    element_volume_m2=frozen(g['volume'].reshape(self.nz,self.nx)),
                    element_flux_m2_s=frozen(volume_flux.reshape(self.nz,self.nx)),
                    weak_divergence_moments_m2_s=frozen(qcontinuity.reshape(self.nz,self.nx,3)),
                    boundary_reaction_force_n_per_m=frozen(np.column_stack((qreaction[:self.nnode],qreaction[self.nnode:]))),
                    diagnostics=diagnostics,geometry_id=self._geometry_id,
                    timings=dict(assembly_seconds=assembled-started,preconditioner_seconds=prepared-assembled,
                                 solve_seconds=solved-prepared,diagnostics_seconds=perf_counter()-solved))
                _cancel(cancel)
                return result

    def top_trace(self, result):
        """Current physical top quadrature for conservative Q2 rate projection."""
        with self._operation(None),self.budget.reserve(4096*self.nx+4096,category='surface-top-trace'):
            g=self._metrics(result['mesh_nodes_m']); edge=self._edge(g,'top')
            velocity=read_array(result['velocity_nodes_m_s'],'result velocity').reshape(self.nnode,2)[self._conn]
            vq=np.einsum('qi,eic->eqc',edge['shape'],velocity[edge['elements']])
            origin=g['pressure_origin'][edge['elements']]; scale=g['pressure_scale'][edge['elements']]
            P=np.concatenate((np.ones((self.nx,self.order,1)),(edge['points']-origin[:,None])/scale[:,None]),axis=-1)
            pc=read_array(result['pressure_coefficients_pa'],'pressure coefficients').reshape(self.elements,3)[edge['elements']]
            basis,_=_q2(self._q)
            return dict(basis=frozen(basis),points_m=frozen(edge['points']),tangent_derivative_m=frozen(edge['tangent']),
                normals=frozen(edge['normal']),arc_weights_m=frozen(edge['weight']),
                dx_weights_m=frozen(edge['tangent'][...,0]*self._qw),velocity_q_m_s=frozen(vq),
                pressure_q_pa=frozen(np.einsum('eqi,ei->eq',P,pc)),
                node_indices=tuple(tuple(range(2*ex,2*ex+3)) for ex in range(self.nx)))

    def laplacian_mesh_velocity(self, mesh_nodes_m, top_vertical_velocity_m_s, *, cancel=None):
        """Q2 harmonic vertical extension; x velocity 0, bottom 0, natural sides.

        Top values are nodal coefficients (2*nx+1,), after the caller's weak
        kinematic projection. This routine does not replace that projection.
        """
        with self._operation(cancel):
            g=self._metrics(mesh_nodes_m)
            if input_shape(top_vertical_velocity_m_s,'top mesh velocity')!=(2*self.nx+1,):
                raise TectonicsError('top mesh velocity needs Q2 nodal coefficients')
            with self.budget.reserve(self.work_bytes,category='surface-mesh-laplacian'):
                local=np.einsum('eq,eqi,eqj->eij',g['weight'],g['gx'],g['gx'])+np.einsum('eq,eqi,eqj->eij',g['weight'],g['gz'],g['gz'])
                matrix=_csr(local,self._conn,self._conn,(self.nnode,self.nnode))
                fixed=np.r_[self._sides['bottom'],self._sides['top']]
                free=np.setdiff1d(np.arange(self.nnode),fixed)
                velocity=np.zeros(self.nnode); velocity[self._sides['top']]=read_array(top_vertical_velocity_m_s,'top mesh velocity')
                rhs=-(matrix@velocity)[free]; reduced=matrix[free,:][:,free]
                if not np.any(rhs):
                    solved=np.zeros_like(rhs); iterations=0; residual=0.
                elif self.method=='direct':
                    solved=splu(reduced.tocsc()).solve(rhs); iterations=1
                    residual=float(np.linalg.norm(reduced@solved-rhs)/np.linalg.norm(rhs))
                    if residual>1e-12:raise TectonicsError('mesh Laplacian direct residual exceeds1e-12')
                else:
                    inverse=self._velocity_inverse(reduced)
                    preconditioner=LinearOperator(reduced.shape,matvec=inverse,dtype=float)
                    solved,iterations,residual=self._gmres(reduced,rhs,preconditioner,cancel)
                velocity[free]=solved
                self._laplacian_diagnostics=dict(linear_residual=residual,iterations=iterations,
                                                geometry_id=self._geometry_id)
                return frozen(velocity.reshape(2*self.nz+1,2*self.nx+1))

    def laplacian_diagnostics(self):
        """Detached diagnostics for the last successfully completed extension."""
        return None if self._laplacian_diagnostics is None else dict(self._laplacian_diagnostics)

    def evaluate_reference(self, result, element_indices, reference_points):
        """Evaluate continuous v, physical P1 p and strain at named element traces.

        element_indices=(N,2) ordered (ez,ex), reference_points=(N,2)=(xi,zeta).
        This avoids silently averaging discontinuous pressure at interfaces.
        Viscosity/stress are not interpolated from quadrature to unknown support.
        """
        count=len(element_indices)
        if count>65536 or input_shape(reference_points)!=(count,2):
            raise TectonicsError('bounded (N,2) reference points required')
        indices=np.asarray(element_indices)
        if indices.shape!=(count,2) or indices.dtype.kind not in 'iu' or np.any(indices<0) or np.any(indices>=np.array([self.nz,self.nx])):
            raise TectonicsError('valid integer element indices required')
        with self._operation(None),self.budget.reserve(4096*count+4096,category='surface-fe-evaluation'):
            g=self._metrics(result['mesh_nodes_m']); reference=read_array(reference_points,'reference points')
            if np.any(np.abs(reference)>1.):raise TectonicsError('reference points outside element')
            elements=indices[:,0]*self.nx+indices[:,1]
            shape,dxi,dze=_basis(reference[:,0],reference[:,1]);xyz=g['xyz'][elements]
            points=np.einsum('ni,nip->np',shape,xyz)
            xx=np.einsum('ni,ni->n',dxi,xyz[...,0]);zx=np.einsum('ni,ni->n',dxi,xyz[...,1]);zz=np.einsum('ni,ni->n',dze,xyz[...,1])
            gx=(dxi-dze*(zx/zz)[:,None])/xx[:,None];gz=dze/zz[:,None]
            local=read_array(result['velocity_nodes_m_s'],'velocity').reshape(self.nnode,2)[self._conn[elements]]
            P=np.c_[np.ones(count),(points-g['pressure_origin'][elements])/g['pressure_scale'][elements]]
            pc=read_array(result['pressure_coefficients_pa'],'pressure').reshape(self.elements,3)[elements]
            strain=np.c_[np.einsum('ni,ni->n',gx,local[...,0]),np.einsum('ni,ni->n',gz,local[...,1]),
                         .5*(np.einsum('ni,ni->n',gz,local[...,0])+np.einsum('ni,ni->n',gx,local[...,1]))]
            return dict(points_m=frozen(points),velocity_m_s=frozen(np.einsum('ni,nic->nc',shape,local)),
                        pressure_pa=frozen(np.einsum('ni,ni->n',P,pc)),strain_s_1=frozen(strain))
