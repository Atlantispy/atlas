"""W04.4: conservative variable-rigidity 1D support with verified mesh refinement.

The weak operator is integral D*w''*v'' + K*w*v, not D times a uniform stencil.
Positive piecewise-constant E/Te/nu and pressure use source-aligned Hermite cells.
Factors are bounded, request-owned and reused; no physical profile changes in time.
"""
from __future__ import annotations

from contextlib import ExitStack
from concurrent.futures import CancelledError
from dataclasses import dataclass, asdict
import hashlib
import json
import math
import threading
import numpy as np
from scipy.linalg import cholesky_banded, cho_solve_banded

from ._validation import TectonicsError, input_shape, snapshot, read_array, frozen, scalar, text
from .finite_flexure import FlexureBoundary1D
from .parameters import FlexureParameters
from .regional import RegionalGrid1D
from .resources import select_budget, reserve_budgets


def _json(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def _cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise CancelledError('variable support cancelled between bounded mesh operations')


def _elastic(e, te, nu):
    if np.any(e <= 0) or np.any(te <= 0) or np.any(nu <= -1) or np.any(nu >= .5):
        raise TectonicsError('positive E/Te and -1 < nu < .5 required')
    with np.errstate(all='ignore'):
        d = np.exp(np.log(e)+3*np.log(te)-math.log(12.)-np.log1p(-nu*nu))
    if not np.isfinite(d).all() or np.any(d <= 0):
        raise TectonicsError('derived rigidity outside numerical range')
    return d


@dataclass(frozen=True, slots=True, init=False)
class RigidityProfile1D:
    grid: RegionalGrid1D
    source_id: str
    frame_id: str
    datum_id: str
    epoch_id: str
    far_left: tuple | None
    far_right: tuple | None
    profile_id: str
    _payload: bytes

    def __init__(self,grid,young_modulus_pa,elastic_thickness_m,poisson_ratio,*,
                 source_id,frame_id,datum_id,epoch_id,far_left=None,far_right=None,budget=None):
        if type(grid) is not RegionalGrid1D:
            raise TectonicsError('explicit regional profile grid required')
        for name,value in dict(source_id=source_id,frame_id=frame_id,datum_id=datum_id,epoch_id=epoch_id).items():
            text(value,name)
        raw_inputs = (young_modulus_pa,elastic_thickness_m,poisson_ratio)
        if any(input_shape(v) != (grid.cells,) for v in raw_inputs):
            raise TectonicsError('one E, Te and nu per ordered source/halo cell required')
        with select_budget(budget).reserve(128*grid.cells+8192):
            arrays = [snapshot(v,name) for v,name in zip(raw_inputs,('E','Te','nu'))]
            if any(a.shape != (grid.cells,) for a in arrays):
                raise TectonicsError('rigidity profile shape changed during capture')
            d = _elastic(*arrays)
            exterior = []
            for value in (far_left,far_right):
                if value is None:
                    exterior.append(None)
                else:
                    if type(value) is not tuple or len(value) != 3:
                        raise TectonicsError('far-field material must be an explicit (E,Te,nu) tuple')
                    a = snapshot(value,'far-field E,Te,nu')
                    _elastic(a[:1],a[1:2],a[2:])
                    exterior.append(tuple(map(float,a)))
            payload = np.column_stack((*arrays,d)).tobytes()
            record = dict(grid=asdict(grid),source_id=source_id,frame_id=frame_id,datum_id=datum_id,
                          epoch_id=epoch_id,far_left=exterior[0],far_right=exterior[1])
            digest = hashlib.sha256(_json(record));digest.update(payload)
            for name,value in dict(grid=grid,source_id=source_id,frame_id=frame_id,datum_id=datum_id,
                    epoch_id=epoch_id,far_left=exterior[0],far_right=exterior[1],
                    profile_id=digest.hexdigest(),_payload=payload).items():
                object.__setattr__(self,name,value)

    @property
    def rigidity_n_m(self):
        return np.frombuffer(self._payload,dtype=float).reshape(-1,4)[:,3]

    @property
    def elastic_thickness_m(self):
        return np.frombuffer(self._payload,dtype=float).reshape(-1,4)[:,1]


@dataclass(frozen=True, slots=True)
class VariableFlexureAccuracy:
    source_id: str
    relative_tolerance: float
    absolute_displacement_m: float
    absolute_slope: float
    absolute_curvature_per_m: float
    max_refinements: int = 6
    max_elements: int = 65536
    max_element_over_alpha: float = .5

    def __post_init__(self):
        text(self.source_id,'numerical policy source')
        for name in ('relative_tolerance','absolute_displacement_m','absolute_slope','absolute_curvature_per_m','max_element_over_alpha'):
            object.__setattr__(self,name,scalar(getattr(self,name),name,positive=True))
        if self.relative_tolerance >= 1 or self.max_element_over_alpha > 1:
            raise TectonicsError('relative tolerance < 1 and element/alpha <= 1 required')
        if type(self.max_refinements) is not int or not 1 <= self.max_refinements <= 8:
            raise TectonicsError('one to eight bounded mesh refinements required')
        if type(self.max_elements) is not int or self.max_elements <= 0:
            raise TectonicsError('positive explicit element ceiling required')


def _shape(s,derivative):
    if derivative == 0:
        return np.array([1-3*s*s+2*s**3,s-2*s*s+s**3,3*s*s-2*s**3,-s*s+s**3])
    if derivative == 1:
        return np.array([-6*s+6*s*s,1-4*s+3*s*s,6*s-6*s*s,-2*s+3*s*s])
    if derivative == 2:
        return np.array([-6+12*s,-4+6*s,6-12*s,-2+6*s])
    return np.array([12.,6.,-12.,6.])


def _band_product(band,x,absolute=False):
    a = np.abs(band) if absolute else band
    y = a[0]*x
    for offset in range(1,len(a)):
        y[offset:] += a[offset,:-offset]*x[:-offset]
        y[:-offset] += a[offset,:-offset]*x[offset:]
    return y


@dataclass(frozen=True, slots=True)
class _Factor:
    subdivisions: int
    elements: int
    h: float
    ndof: int
    bandwidth: int
    dofs_bytes: bytes
    band_bytes: bytes
    cholesky_bytes: bytes
    scale_bytes: bytes
    endpoint_bytes: bytes
    constrained: tuple

    @property
    def bytes(self):
        return sum(len(v) for v in (self.dofs_bytes,self.band_bytes,self.cholesky_bytes,self.scale_bytes,self.endpoint_bytes))


class VariableRigidityFlexure:
    """Request-owned fixed profile, bounded lazy factor reuse and mesh-change gate.

solve returns (source cells,5,4). Rows 0/1/2: one-sided left/centre/right
(w,w',w'',w'''). Row3: FE polynomial maxima (abs w,slope,curvature,strain).
Row4: mesh-change estimates (w,slope,curvature,accepted subdivisions).
Refinement is numerical evidence, not a rigorous continuum-error certificate.
"""
    def __setattr__(self,name,value):
        if getattr(self,'_sealed',False):
            raise AttributeError('variable support definition is immutable')
        object.__setattr__(self,name,value)

    def __init__(self,profile,parameters,boundary,accuracy,*,budget=None):
        if (type(profile) is not RigidityProfile1D or type(parameters) is not FlexureParameters
                or type(accuracy) is not VariableFlexureAccuracy):
            raise TectonicsError('typed profile, restoring parameters and accuracy required')
        if boundary != 'periodic' and type(boundary) is not FlexureBoundary1D:
            raise TectonicsError('explicit periodic or typed finite boundary required')
        continuous = boundary != 'periodic' and boundary.continuous
        if continuous != (profile.far_left is not None and profile.far_right is not None):
            raise TectonicsError('continuous support needs both explicit exterior materials')
        if not continuous and (profile.far_left is not None or profile.far_right is not None):
            raise TectonicsError('physical/periodic profiles cannot include exterior materials')
        self.profile=profile;self.parameters=parameters;self.boundary=boundary;self.accuracy=accuracy
        self.grid=profile.grid;self._budget=select_budget(budget)
        self._stack=ExitStack();self._levels={};self._lock=threading.RLock();self._closed=False
        k=parameters.restoring_pa_per_m
        alpha=np.exp((math.log(4.)+np.log(profile.rigidity_n_m)-math.log(k))/4)
        ratio=self.grid.spacing_m/(float(np.min(alpha))*accuracy.max_element_over_alpha)
        if not math.isfinite(ratio):
            raise TectonicsError('required variable-rigidity mesh outside numerical range')
        self.base_subdivisions=max(1,math.ceil(ratio))
        if 2*self.grid.cells*self.base_subdivisions > accuracy.max_elements:
            raise TectonicsError('base and comparison meshes exceed the explicit element ceiling')
        self.operator_id=hashlib.sha256(_json(dict(method='hermite-consistent-variable-D-banded-refined-v1',
            profile=profile.profile_id,K=k,gravity=parameters.gravity_m_s2,
            boundary=boundary if boundary=='periodic' else asdict(boundary),accuracy=asdict(accuracy)))).hexdigest()
        self._sealed=True

    @property
    def setup_bytes(self):
        return sum(f.bytes for f in self._levels.values())

    def _factor(self,subdivisions,budget=None):
        with self._lock:
            if self._closed: raise TectonicsError('variable support is closed')
            if subdivisions in self._levels: return self._levels[subdivisions]
            m=self.grid.cells*subdivisions
            if m > self.accuracy.max_elements:
                raise TectonicsError('mesh refinement exceeds explicit element ceiling')
            with reserve_budgets(4096*m+65536,self._budget,select_budget(budget if budget is not None else self._budget),
                                category='variable-flexure-setup'):
                h=self.grid.spacing_m/subdivisions;k=self.parameters.restoring_pa_per_m
                t=np.exp(np.log(np.repeat(self.profile.rigidity_n_m,subdivisions))-math.log(k)-4*math.log(h))
                if not np.isfinite(t).all() or np.any(t<=0):
                    raise TectonicsError('scaled bending stiffness outside numerical range')
                periodic=self.boundary=='periodic'
                nodes=m if periodic else m+1;ndof=2*nodes
                permutation=np.arange(nodes)
                if periodic:
                    # Fold the ring: neighbours become at most two node blocks
                    # apart, retaining constant-bandwidth Cholesky (no dense seam).
                    order=np.empty(nodes,dtype=np.intp);order[0]=0
                    order[1::2]=np.arange(1,1+len(order[1::2]))
                    order[2::2]=np.arange(nodes-1,nodes-1-len(order[2::2]),-1)
                    permutation[order]=np.arange(nodes)
                left=permutation[np.arange(m)];right=permutation[(np.arange(m)+1)%nodes]
                dofs=np.column_stack((2*left,2*left+1,2*right,2*right+1)).astype(np.intp)
                width=min(5 if periodic else 3,ndof-1)
                band=np.zeros((width+1,ndof))
                bending=np.array([[12,6,-12,6],[6,4,-6,2],[-12,-6,12,-6],[6,2,-6,4]],float)
                foundation=np.array([[156,22,54,-13],[22,4,13,-3],[54,13,156,-22],[-13,-3,-22,4]],float)/420
                for a in range(4):
                    for b in range(a+1):
                        row=np.maximum(dofs[:,a],dofs[:,b]);col=np.minimum(dofs[:,a],dofs[:,b])
                        value=t*bending[a,b]+foundation[a,b]
                        if a!=b: value=value*np.where(row==col,2.,1.)
                        np.add.at(band,(row-col,col),value)
                endpoints=np.zeros((2,2,2))
                constrained=[]
                if not periodic:
                    if self.boundary.continuous:
                        for side,material in enumerate((self.profile.far_left,self.profile.far_right)):
                            d=float(_elastic(np.array(material[:1]),np.array(material[1:2]),np.array(material[2:]))[0])
                            alpha=math.exp((math.log(4.)+math.log(d)-math.log(k))/4)
                            r=alpha/h;sign=-1 if side==0 else 1
                            endpoints[side]=[[r,sign*r*r/2],[sign*r*r/2,r*r*r/2]]
                            base=0 if side==0 else ndof-2
                            band[0,base:base+2]+=np.diag(endpoints[side])
                            band[1,base]+=endpoints[side,1,0]
                    else:
                        for side,mode in enumerate((self.boundary.left,self.boundary.right)):
                            if mode=='clamped': constrained.extend((0,1) if side==0 else (ndof-2,ndof-1))
                for index in constrained:
                    for offset in range(1,width+1):
                        if index+offset<ndof: band[offset,index]=0.
                        if index-offset>=0: band[offset,index-offset]=0.
                    band[0,index]=1.
                scale=1/np.sqrt(band[0])
                for offset in range(width+1):
                    stop=ndof-offset
                    band[offset,:stop]*=scale[offset:]*scale[:stop]
                if not np.isfinite(band).all() or not np.isfinite(scale).all():
                    raise TectonicsError('variable support matrix outside numerical range')
                try: chol=cholesky_banded(band,lower=True,check_finite=False)
                except np.linalg.LinAlgError as exc:
                    raise TectonicsError('variable support factorisation failed; no stiffness jitter/fallback') from exc
                factor=_Factor(subdivisions,m,h,ndof,width,dofs.tobytes(),band.tobytes(),chol.tobytes(),
                               scale.tobytes(),endpoints.tobytes(),tuple(constrained))
                # Admit retained ownership while construction work is still
                # charged: refusal cannot leave an unaccounted cached factor.
                self._stack.enter_context(self._budget.reserve(factor.bytes,category='variable-flexure-retained'))
                self._levels[subdivisions]=factor
                return factor

    def work_bytes(self,shape):
        if shape!=(self.grid.cells+2,):
            raise TectonicsError('N pressure cells plus two explicit far-field pressures required')
        return 512*self.grid.cells+8192

    def _linear_solve(self,f,rhs):
        scale=np.frombuffer(f.scale_bytes);band=np.frombuffer(f.band_bytes).reshape(f.bandwidth+1,f.ndof)
        chol=np.frombuffer(f.cholesky_bytes).reshape(band.shape)
        rhs=rhs.copy();rhs[list(f.constrained)]=0.
        scaled=rhs*scale
        z=cho_solve_banded((chol,True),scaled,check_finite=False)
        residual=_band_product(band,z)-scaled
        allowance=1024*np.finfo(float).eps*(_band_product(band,np.abs(z),absolute=True)+np.abs(scaled))
        if not np.isfinite(z).all() or np.any(np.abs(residual)>allowance+np.finfo(float).tiny):
            raise TectonicsError('variable support failed scaled equation residual')
        return z*scale

    def _response(self,f,load,budget=None):
        h=f.h;m=f.elements;k=self.parameters.restoring_pa_per_m
        with reserve_budgets(2048*m+65536,self._budget,select_budget(budget if budget is not None else self._budget),
                            category='variable-flexure-response'):
            dofs=np.frombuffer(f.dofs_bytes,dtype=np.intp).reshape(m,4)
            with np.errstate(over='ignore',under='ignore'):
                scaled_load=load/k
            if not np.isfinite(scaled_load).all() or np.any((load!=0)&(scaled_load==0)):
                raise TectonicsError('scaled pressure outside numerical range')
            q=scaled_load[:-2]
            unclamped=self.boundary=='periodic' or self.boundary.continuous or (
                self.boundary.left=='free' and self.boundary.right=='free')
            offset=math.fsum(map(float,q/len(q))) if unclamped else 0.
            q=np.repeat(q-offset,f.subdivisions)
            rhs=np.zeros(f.ndof)
            for a,weight in enumerate((.5,1/12,.5,-1/12)):
                np.add.at(rhs,dofs[:,a],weight*q)
            if self.boundary!='periodic' and self.boundary.continuous:
                endpoint=np.frombuffer(f.endpoint_bytes).reshape(2,2,2)
                rhs[:2]+=endpoint[0,:,0]*(scaled_load[-2]-offset)
                rhs[-2:]+=endpoint[1,:,0]*(scaled_load[-1]-offset)
            u=self._linear_solve(f,rhs)
            local=u[dofs]
            out=np.zeros((self.grid.cells,5,4))
            # Source interfaces are sampled one-sided, including D jumps.
            for where,(element,s) in enumerate(((0,0.),(f.subdivisions//2,0. if f.subdivisions%2==0 else .5),
                                               (f.subdivisions-1,1.))):
                row=local[np.arange(self.grid.cells)*f.subdivisions+element]
                for d in range(4): out[:,where,d]=(row@_shape(s,d))/h**d
                if where==1 and f.subdivisions%2==0:
                    # The source centre is an artificial internal FE face,
                    # not a material interface. Average its two traces so the
                    # sampling convention respects reflection. Source faces
                    # remain strictly one-sided across physical D jumps.
                    other=local[np.arange(self.grid.cells)*f.subdivisions+element-1]
                    for d in range(4):
                        out[:,where,d]=.5*(out[:,where,d]+(other@_shape(1.,d))/h**d)
                out[:,where,0]+=offset
            # Exact extrema of the represented cubic FE polynomial on each
            # element. No smoothed interface curvature or centre-only strain.
            a0=local[:,0]+offset;a1=local[:,1]
            a2=-3*local[:,0]-2*local[:,1]+3*local[:,2]-local[:,3]
            a3=2*local[:,0]+local[:,1]-2*local[:,2]+local[:,3]
            def value(s): return ((a3*s+a2)*s+a1)*s+a0
            maximum_w=np.maximum(np.abs(a0),np.abs(value(1.)))
            maximum_slope=np.maximum(np.abs(a1),np.abs(a1+2*a2+3*a3))
            with np.errstate(divide='ignore',invalid='ignore',over='ignore'):
                vertex=-a2/(3*a3)
                slope=np.abs(a1+2*a2*vertex+3*a3*vertex*vertex)
                maximum_slope=np.maximum(maximum_slope,np.where((vertex>0)&(vertex<1),slope,0.))
                discriminant=4*a2*a2-12*a3*a1
                root=np.sqrt(np.maximum(discriminant,0.))
                # Stable quadratic roots for w'=0; linear derivative separately.
                qroot=-a2-np.copysign(root/2,a2)
                roots=(qroot/(3*a3),a1/qroot,np.where(a3==0,-a1/(2*a2),np.nan))
                for s in roots:
                    valid=(s>0)&(s<1)&((discriminant>=0)|(a3==0))
                    maximum_w=np.maximum(maximum_w,np.where(valid,np.abs(value(s)),0.))
            maximum_curvature=np.maximum(np.abs(2*a2),np.abs(2*a2+6*a3))/h**2
            for d,values in enumerate((maximum_w,maximum_slope/h,maximum_curvature)):
                out[:,3,d]=values.reshape(self.grid.cells,f.subdivisions).max(axis=1)
            out[:,3,3]=out[:,3,2]*self.profile.elastic_thickness_m/2
            return frozen(out)

    def solve(self,packed_load_pa,*,budget=None,cancel=None):
        if self._closed: raise TectonicsError('variable support is closed')
        _cancel(cancel)
        shape=input_shape(packed_load_pa,'variable support load')
        with reserve_budgets(self.work_bytes(shape),self._budget,
                            select_budget(budget if budget is not None else self._budget)):
            load=read_array(packed_load_pa,'variable support load',ndim=1)
            continuous=self.boundary!='periodic' and self.boundary.continuous
            if not continuous and np.any(load[-2:]!=0):
                raise TectonicsError('physical/periodic support cannot include exterior pressures')
            old=None
            atol=np.array([self.accuracy.absolute_displacement_m,self.accuracy.absolute_slope,
                           self.accuracy.absolute_curvature_per_m])
            for level in range(self.accuracy.max_refinements+1):
                _cancel(cancel)
                subdivisions=self.base_subdivisions*2**level
                current=self._response(self._factor(subdivisions,budget),load,budget)
                _cancel(cancel)
                if old is not None:
                    error=np.maximum(np.max(np.abs(current[:,:3,:3]-old[:,:3,:3]),axis=1),
                                     np.abs(current[:,3,:3]-old[:,3,:3]))
                    magnitude=np.max(current[:,3,:3],axis=0)
                    if np.all(error<=atol+self.accuracy.relative_tolerance*magnitude):
                        out=current.copy();out[:,4,:3]=error;out[:,4,3]=subdivisions
                        return frozen(out)
                old=current
            raise TectonicsError('variable support mesh-change tolerance not reached within refinement ceiling')

    def close(self):
        with self._lock:
            if not self._closed:
                object.__setattr__(self,'_closed',True)
                self._levels.clear();self._stack.close()

    def __enter__(self):
        if self._closed: raise TectonicsError('variable support is closed')
        return self

    def __exit__(self,*args): self.close()
