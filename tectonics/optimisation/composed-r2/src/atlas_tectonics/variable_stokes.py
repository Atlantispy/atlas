"""R4.3: symmetric-stress MAC discretisation, not eta times a Laplacian.

SPDX-License-Identifier: AGPL-3.0-only

Uniform closed free-slip rectangles only. Normal strains are cell-centred,
engineering shear gamma=du/dz+dw/dx is at interior vertices. The stress is
(2*eta_c*exx, 2*eta_c*ezz, eta_v*gamma). Boundary shear traction is zero;
normal boundary velocities are eliminated. The velocity matrix is
2 Bx.T eta_c Bx + 2 Bz.T eta_c Bz + S.T eta_v S. Its positive quadratic
form is the discrete integral of 2*eta*e:e, not |grad(u)|^2 at variable eta.
The unchanged divergence/pressure gauge is inherited from the R4.1 support.

The stencil and independent derivative-matrix assembly agree without obtaining
matrix columns by probing the stencil. Sparse derivatives/topology are prepared
once; numerical viscosity and preconditioner factors are never reused after a
coefficient change. This module adds no evolution, damage law, or mesh repair.
"""
from __future__ import annotations
from dataclasses import dataclass
import math
import numpy as np
try:
    from scipy.sparse import coo_matrix, bmat, diags, csc_matrix
except ImportError:
    coo_matrix = bmat = diags = csc_matrix = None
from ._validation import TectonicsError, scalar
from .constitutive import DiffusiveScales, RheologyProfile
from .stokes import StokesBox2D, _MACOperator

_METHOD = 'atlas.variable-stress-mac-2d.v1'


@dataclass(frozen=True, slots=True)
class NonlinearStokesPolicy:
    """Explicit work and error limits; no silent law/mesh/precision fallback.

    GMRES uses a bounded restarted basis and a block-triangular preconditioner
    with ILU or a fixed linear geometric velocity V-cycle. Auto selects GMG
    only on assessed size/workload supports; MINRES is not valid for this block.
    Numerical fill is admitted conservatively before native factorisation; this
    accounting is not an operating-system RSS cap. Nonlinear acceptance always
    checks the true newly evaluated law at the returned physical fields.
    """
    method: str = 'gmres'
    max_unknowns: int = 200_000
    direct_max_unknowns: int = 4096
    restart: int = 60
    max_cycles: int = 20
    linear_rtol: float = 1e-12
    max_picard_iterations: int = 100
    relaxation: float = 1.0
    momentum_tolerance: float = 1e-9
    divergence_tolerance: float = 1e-10
    gauge_tolerance: float = 1e-12
    work_balance_tolerance: float = 1e-9
    viscosity_rtol: float = 1e-8
    ilu_drop_tolerance: float = 1e-4
    ilu_fill_factor: float = 12.0
    max_viscosity_contrast: float = 1e12
    velocity_preconditioner: str = 'auto'

    def __post_init__(self):
        if self.method not in ('gmres', 'direct'):
            raise TectonicsError('variable mechanics requires gmres or explicit direct reference')
        if self.velocity_preconditioner not in ('auto', 'ilu', 'gmg'):
            raise TectonicsError('velocity preconditioner must be auto, ilu or gmg')
        if self.method == 'direct' and self.velocity_preconditioner == 'gmg':
            raise TectonicsError('multigrid requires GMRES')
        for key in ('max_unknowns','direct_max_unknowns','restart','max_cycles','max_picard_iterations'):
            if type(getattr(self,key)) is not int or getattr(self,key)<1:
                raise TectonicsError(key+' must be a positive integer')
        if self.restart>512 or self.max_picard_iterations>10000 or self.max_cycles>10000:
            raise TectonicsError('iteration policy exceeds supported finite envelope')
        for key in ('linear_rtol','momentum_tolerance','divergence_tolerance','gauge_tolerance',
                    'work_balance_tolerance','viscosity_rtol'):
            value=scalar(getattr(self,key),key,positive=True)
            if not np.finfo(float).eps<=value<=1e-3:
                raise TectonicsError(key+' outside binary64 error-policy envelope')
            object.__setattr__(self,key,value)
        for key,lo,hi in (('relaxation',0.,1.),('ilu_drop_tolerance',0.,.1),
                          ('ilu_fill_factor',1.,100.),('max_viscosity_contrast',1.,1e30)):
            value=scalar(getattr(self,key),key,nonnegative=True)
            if not lo<=value<=hi or (key=='relaxation' and value==0):
                raise TectonicsError(key+' outside numerical policy envelope')
            object.__setattr__(self,key,value)


def check_variable_support(box,scales):
    if type(box) is not StokesBox2D or type(scales) is not DiffusiveScales:
        raise TectonicsError('typed box and diffusive scales required')
    hx=scalar((box.width_m/scales.length_m)/box.nx,'scaled x spacing',positive=True)
    hz=scalar((box.height_m/scales.length_m)/box.nz,'scaled z spacing',positive=True)
    try: coeff=(1/hx)**2+(1/hz)**2
    except OverflowError as exc: raise TectonicsError('variable-stress coefficients outside range') from exc
    if not math.isfinite(coeff) or coeff==0:
        raise TectonicsError('variable-stress coefficients outside range')
    return hx,hz


def check_coupled_rheology(box,scales,profile):
    """Only existing constant/Tosi laws can evolve without an extra damage field.

    BF memory is supported by the separate mechanical snapshot with an explicitly
    supplied frozen damage field, never silently zeroed/advected by the two-field
    thermochemical state. No pressure-sensitive yield or new thermal law is chosen.
    """
    check_variable_support(box,scales)
    if type(profile) is not RheologyProfile or profile.family not in ('constant','tosi-linear','tosi-plastic'):
        raise TectonicsError('coupled R4.3 supports constant/Tosi laws; damage evolution needs a named extension')
    if box.height_m>scales.depth_scale_m:
        raise TectonicsError('box extends outside declared rheology depth normalisation')


class _StressMACOperator(_MACOperator):
    """Unchecked private native arrays; preparation/solve owns admission and limits."""
    def __init__(self,box,hx,hz,*,compiled=False):
        super().__init__(box,hx,hz)
        self._native=None
        if compiled:
            from . import _mechanics_native
            _mechanics_native.prepare()
            self._native=_mechanics_native
        if coo_matrix is None:
            raise TectonicsError('SciPy sparse operators unavailable')
        self._build_derivatives()
        if compiled:self._build_velocity_template()
        else:self.velocity_template_nbytes=0
        self.eta_c=np.ones((self.nz,self.nx))
        self.eta_v=np.ones((self.nz-1,self.nx-1))

    def _build_derivatives(self):
        u=np.arange(self.nu).reshape(self.nz,self.nx-1)
        w=np.arange(self.nw).reshape(self.nz-1,self.nx)+self.nu
        p=np.arange(self.np).reshape(self.nz,self.nx)
        def matrix(rows,cols,values,nrows):
            return coo_matrix((np.concatenate(values),(np.concatenate(rows),np.concatenate(cols))),
                              shape=(nrows,self.nv)).tocsr()
        self.bx=matrix([p[:,:-1].ravel(),p[:,1:].ravel()],[u.ravel(),u.ravel()],
                       [np.full(self.nu,1/self.hx),np.full(self.nu,-1/self.hx)],self.np)
        self.bz=matrix([p[:-1].ravel(),p[1:].ravel()],[w.ravel(),w.ravel()],
                       [np.full(self.nw,1/self.hz),np.full(self.nw,-1/self.hz)],self.np)
        n=(self.nz-1)*(self.nx-1);v=np.arange(n)
        self.shear=matrix([v,v,v,v],[u[1:].ravel(),u[:-1].ravel(),w[:,1:].ravel(),w[:,:-1].ravel()],
                          [np.full(n,1/self.hz),np.full(n,-1/self.hz),
                           np.full(n,1/self.hx),np.full(n,-1/self.hx)],n)
        self.d=(self.bx+self.bz).tocsr()
        self.g=(-self.d.T).tocsc()
        self.cvec=coo_matrix((np.full(self.np,self.c),(np.arange(self.np),np.zeros(self.np,dtype=int))),
                             shape=(self.np,1)).tocsc()

    def _build_velocity_template(self):
        """Prepare the fixed CSC pattern and exact predecessor contribution order.

        Bx/Bz rows contribute centre viscosity and shear rows contribute vertex
        viscosity.  Terms are sorted stably by final CSC entry, preserving their
        predecessor component/source order inside each entry.  No numerical
        viscosity value is retained in this geometry-only template.
        """
        chunks=[]
        for matrix,offset,component in ((self.bx,0,0),(self.bz,0,1),(self.shear,self.np,2)):
            matrix=matrix.tocsr();lengths=np.diff(matrix.indptr)
            for width in np.unique(lengths):
                width=int(width)
                if width==0:continue
                source=np.flatnonzero(lengths==width);starts=matrix.indptr[source]
                locations=starts[:,None]+np.arange(width)[None,:]
                indices=matrix.indices[locations];values=matrix.data[locations]
                rows=np.broadcast_to(indices[:,:,None],(len(source),width,width)).reshape(-1).astype(np.int32)
                cols=np.broadcast_to(indices[:,None,:],(len(source),width,width)).reshape(-1).astype(np.int32)
                coefficients=np.repeat((offset+source).astype(np.int32),width*width)
                left=np.broadcast_to(values[:,:,None],(len(source),width,width)).reshape(-1).copy()
                right=np.broadcast_to(values[:,None,:],(len(source),width,width)).reshape(-1).copy()
                components=np.full(len(coefficients),component,dtype=np.uint8)
                chunks.append((rows,cols,coefficients,left,right,components))
        rows=np.concatenate([x[0] for x in chunks]);cols=np.concatenate([x[1] for x in chunks])
        coefficient=np.concatenate([x[2] for x in chunks]);left=np.concatenate([x[3] for x in chunks])
        right=np.concatenate([x[4] for x in chunks]);component=np.concatenate([x[5] for x in chunks]);del chunks
        key=cols.astype(np.int64)*self.nv+rows.astype(np.int64);del rows,cols
        unique,entry=np.unique(key,return_inverse=True);del key
        order=np.argsort(entry,kind='stable');entry=entry[order]
        coefficient=coefficient[order];left=left[order];right=right[order];component=component[order]
        counts=np.bincount(entry,minlength=len(unique));term_indptr=np.empty(len(unique)+1,dtype=np.int32)
        term_indptr[0]=0;np.cumsum(counts,out=term_indptr[1:]);del entry,counts,order
        column=(unique//self.nv).astype(np.int32);indices=(unique%self.nv).astype(np.int32);del unique
        counts=np.bincount(column,minlength=self.nv);indptr=np.empty(self.nv+1,dtype=np.int32);indptr[0]=0
        np.cumsum(counts,out=indptr[1:]);del column,counts
        self._velocity_indices=indices;self._velocity_indptr=indptr;self._velocity_term_indptr=term_indptr
        self._velocity_term_component=component;self._velocity_term_coefficient=coefficient
        self._velocity_term_left=left;self._velocity_term_right=right
        values=(self._velocity_indices,self._velocity_indptr,self._velocity_term_indptr,
                self._velocity_term_component,self._velocity_term_coefficient,
                self._velocity_term_left,self._velocity_term_right)
        for value in values:value.setflags(write=False)
        self.velocity_template_nbytes=sum(value.nbytes for value in values)

    def set_viscosity(self,cell,vertex):
        self.eta_c=cell;self.eta_v=vertex

    def strains(self,u,w):
        # Form the eliminated zero-normal-wall differences directly.  This is
        # algebraically the same MAC stencil as padding with zero wall faces,
        # but avoids two padded temporary arrays on every matrix-vector call.
        a=np.empty((self.nz,self.nx));b=np.empty((self.nz,self.nx))
        a[:,0]=u[:,0]/self.hx;a[:,-1]=-u[:,-1]/self.hx
        a[:,1:-1]=np.diff(u,axis=1)/self.hx
        b[0]=w[0]/self.hz;b[-1]=-w[-1]/self.hz
        b[1:-1]=np.diff(w,axis=0)/self.hz
        return (a,b,np.diff(u,axis=0)/self.hz+np.diff(w,axis=1)/self.hx)

    def velocity(self,u,w):
        a,b,gamma=self.strains(u,w)
        xx=2*self.eta_c*a;zz=2*self.eta_c*b;shear=self.eta_v*gamma
        au=-np.diff(xx,axis=1)/self.hx
        aw=-np.diff(zz,axis=0)/self.hz
        # Zero shear traction at the outer vertices, written without np.pad.
        au[0]-=shear[0]/self.hz;au[-1]+=shear[-1]/self.hz
        au[1:-1]-=np.diff(shear,axis=0)/self.hz
        aw[:,0]-=shear[:,0]/self.hx;aw[:,-1]+=shear[:,-1]/self.hx
        aw[:,1:-1]-=np.diff(shear,axis=1)/self.hx
        return au,aw

    def matvec(self,vector):
        # Explicit prepared native path; the NumPy operator and independent
        # returned-field residual checks remain separate verification routes.
        # A fresh returned vector is essential: GMRES can keep/mutate old ones.
        if self._native is None:
            return super().matvec(vector)
        # SciPy also permits an (N, 1) matvec input (including matmat fallback).
        # Normalise its view and reject wrong lengths before unchecked native access.
        vector=vector.reshape(self.n)
        pressure_sum=float(np.sum(vector[self.nv:-1]))
        return self._native.stress_saddle(vector,self.eta_c,self.eta_v,
                                         self.hx,self.hz,self.c,pressure_sum)

    def velocity_matrix(self):
        # The explicit sparse-direct reference retains the predecessor SciPy
        # assembly.  GMRES alone reuses the geometry-only symbolic template;
        # numerical viscosity values and factors are still rebuilt as required.
        if self._native is None:
            centre=(2*self.eta_c.ravel())[:,None];vertex=self.eta_v.ravel()[:,None]
            return (self.bx.T@self.bx.multiply(centre)+self.bz.T@self.bz.multiply(centre)+
                    self.shear.T@self.shear.multiply(vertex)).tocsc()
        data=self._native.weighted_velocity_data(self._velocity_term_indptr,self._velocity_term_component,
            self._velocity_term_coefficient,self._velocity_term_left,self._velocity_term_right,
            self.eta_c,self.eta_v,self.np,len(self._velocity_indices))
        return csc_matrix((data,self._velocity_indices,self._velocity_indptr),shape=(self.nv,self.nv),copy=False)

    def sparse_reference(self):
        a=self.velocity_matrix()
        return bmat([[a,self.g,None],[self.g.T,None,self.cvec],[None,self.cvec.T,None]],format='csc')

    def energy(self,u,w):
        a,b,gamma=self.strains(u,w)
        return float((np.sum(2*self.eta_c*(a*a+b*b))+np.sum(self.eta_v*gamma*gamma))*self.hx*self.hz)

    def invariant_sites(self,u,w):
        """eII=sqrt(e:e/2) at each stress site, in the velocity's supplied units.

        Reconstruct missing tensor components by symmetric arithmetic averages,
        not viscosity averages. A corner has zero wall shear. Centre invariant
        uses a/b there and the four-corner average shear; vertex invariant uses
        the local shear and adjacent-centre a/b averages. This is a registered
        second-order collocation choice, not a subcell localisation model.
        """
        a,b,g=self.strains(u,w)
        gp=np.pad(g,1)
        gc=.25*(gp[:-1,:-1]+gp[1:,:-1]+gp[:-1,1:]+gp[1:,1:])
        av=.25*(a[:-1,:-1]+a[1:,:-1]+a[:-1,1:]+a[1:,1:])
        bv=.25*(b[:-1,:-1]+b[1:,:-1]+b[:-1,1:]+b[1:,1:])
        # hypot avoids an unnecessary square overflow or underflow.
        return (np.hypot(np.hypot(a,b)/math.sqrt(2.),gc*.5),
                np.hypot(np.hypot(av,bv)/math.sqrt(2.),g*.5))


def _stress_residuals(op,u,w,p,fx,fz):
    """Independent face-balance expressions (not sparse K*x or velocity())."""
    uf=np.zeros((op.nz,op.nx+1));wf=np.zeros((op.nz+1,op.nx))
    uf[:,1:-1]=u;wf[1:-1]=w
    ex=(uf[:,1:]-uf[:,:-1])/op.hx
    ez=(wf[1:]-wf[:-1])/op.hz
    shear=np.zeros((op.nz+1,op.nx+1))
    shear[1:-1,1:-1]=op.eta_v*((uf[1:,1:-1]-uf[:-1,1:-1])/op.hz+
                                        (wf[1:-1,1:]-wf[1:-1,:-1])/op.hx)
    ru=(p[:,1:]-p[:,:-1]-2*(op.eta_c[:,1:]*ex[:,1:]-op.eta_c[:,:-1]*ex[:,:-1]))/op.hx
    rw=(p[1:]-p[:-1]-2*(op.eta_c[1:]*ez[1:]-op.eta_c[:-1]*ez[:-1]))/op.hz
    ru-=(shear[1:,1:-1]-shear[:-1,1:-1])/op.hz+fx
    rw-=(shear[1:-1,1:]-shear[1:-1,:-1])/op.hx+fz
    divergence=ex+ez
    # Evaluate work separately with stress-site tensor contraction.
    dissipation=(np.sum(2*op.eta_c*(ex*ex+ez*ez))+
        np.sum(shear[1:-1,1:-1]*((uf[1:,1:-1]-uf[:-1,1:-1])/op.hz+
                                (wf[1:-1,1:]-wf[1:-1,:-1])/op.hx)))*op.hx*op.hz
    return ru,rw,divergence,float(dissipation)
