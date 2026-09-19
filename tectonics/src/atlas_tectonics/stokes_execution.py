"""R4.1 source-bound steady Stokes solves, reuse, diagnostics and snapshots.

SPDX-License-Identifier: AGPL-3.0-only
R4 IS IN PROGRESS. This implements only the constant-viscosity mechanical
increment. It does not step temperature/composition, predict plate labels,
solve nonlinear viscosity/yielding or complete a convection benchmark.

The existing WorkBudget, ExecutionContext, native-thread lease and ArrayStore
are reused. Globally coupled velocities/pressure are never separate plate jobs.
Preparation retains a spectral preconditioner (normal path), or explicitly a
small sparse LU (independent reference), for repeated forcing snapshots. Native
factorisation/FFT calls finish before cancellation can release their admission.
A result is a self-contained steady record, NOT a restartable evolving world.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json
import math
import threading

import numpy as np
try:
    from scipy.sparse.linalg import LinearOperator, minres, splu
except ImportError:
    LinearOperator = minres = splu = None

from ._validation import TectonicsError, text, scalar, input_shape, read_array, frozen
from .resources import select_budget
from .reuse import ExecutionContext
from .execution import _acquire_native_limit, _release_native_limit
from .constitutive import DiffusiveScales, RheologyProfile, _json, _cancel
from .stokes import (StokesBox2D, StokesSolvePolicy, _scaling, _MACOperator,
                     _SeparableVelocityInverse, _METHOD, _BOUNDARY, _GAUGE)


def _digest(value):
    return hashlib.sha256(_json(value)).hexdigest()


def _hex(value, name):
    if not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):
        raise TectonicsError('invalid '+name+' digest')


@contextmanager
def _native_lease():
    # Use the already coordinated process-wide lease, not a competing threadpool
    # controller. FFT workers are also explicitly one in the preconditioner.
    _acquire_native_limit(1)
    try:
        yield
    finally:
        _release_native_limit()


def _checked_scale(array, scale, name, *, divide=False):
    """Refuse unavailable SI conversions rather than silently erase nonzero data."""
    with np.errstate(over='raise',invalid='raise',divide='raise',under='ignore'):
        try:
            value = array/scale if divide else array*scale
        except FloatingPointError as exc:
            raise TectonicsError(name+' is outside finite binary64 range') from exc
    if np.any((value==0)&(array!=0)):
        raise TectonicsError(name+' underflows binary64 output')
    if not np.all(np.isfinite(value)):
        raise TectonicsError(name+' is outside finite binary64 range')
    return value


def _factored_scale(array, numerator, denominator, name):
    """Evaluate array * prod(numerator)/prod(denominator) without range loss.

    Factors are positive finite SI scales already validated by the prepared
    problem. Only mantissas are multiplied/divided; exponents remain integers
    until a normal scalar factor or the final ldexp. This avoids a subnormal
    *intermediate* scale silently
    losing significant bits, or an overflowing scale with a finite final field.
    Final subnormals are kept. A nonzero value rounded to zero is refused, while
    the complete published-field equation gates decide adequacy of nonzero
    rounded output. Scratch belongs to the existing stokes-solve reservation.
    """
    mantissa, exponent = 1., 0
    for factor in numerator:
        m, e = math.frexp(factor)
        mantissa *= m; exponent += e
    for factor in denominator:
        m, e = math.frexp(factor)
        mantissa /= m; exponent -= e
    mantissa, shift = math.frexp(mantissa)
    exponent += shift
    # A single NORMAL scalar factor has full binary64 precision and needs only
    # one native multiplication. Do not materialise a subnormal or overflowing
    # factor: that is the range where combining exponents with each array entry
    # is essential. The returned-field gates still check final output rounding.
    if -1021 <= exponent <= 1023:
        return _checked_scale(array,math.ldexp(mantissa,exponent),name)
    with np.errstate(over='raise', invalid='raise', under='ignore'):
        try:
            values, powers = np.frexp(array)
            values *= mantissa
            np.ldexp(values, powers+exponent, out=values)
        except FloatingPointError as exc:
            raise TectonicsError(name+' is outside finite binary64 range') from exc
    if not np.all(np.isfinite(values)):
        raise TectonicsError(name+' is outside finite binary64 range')
    if np.any((values == 0) & (array != 0)):
        raise TectonicsError(name+' underflows binary64 output')
    return values


def _residual_fields(op,u,w,p,fx,fz):
    """Independent ghost/central-difference check, not K*x from either solver.

    A pressure gauge multiplier must not hide a continuity error here. Normal
    wall fluxes are zero; tangential ghosts are even reflections for free slip.
    """
    ih,iz = (1/op.hx)**2,(1/op.hz)**2
    un = np.pad(u,((0,0),(1,1)),mode='constant')
    ut = np.pad(u,((1,1),(0,0)),mode='edge')
    wn = np.pad(w,((1,1),(0,0)),mode='constant')
    wt = np.pad(w,((0,0),(1,1)),mode='edge')
    ru = -ih*(un[:,2:]-2*u+un[:,:-2])-iz*(ut[2:]-2*u+ut[:-2])+np.diff(p,axis=1)/op.hx-fx
    rw = -iz*(wn[2:]-2*w+wn[:-2])-ih*(wt[:,2:]-2*w+wt[:,:-2])+np.diff(p,axis=0)/op.hz-fz
    divergence = np.diff(un,axis=1)/op.hx+np.diff(wn,axis=0)/op.hz
    return ru,rw,divergence


def _diagnostics(op,vector,rhs,policy):
    u,w,p,gauge = op.split(vector)
    fx,fz,_,_ = op.split(rhs)
    ru,rw,div = _residual_fields(op,u,w,p,fx,fz)
    # The caller normalises max|forcing| to one (unless it is identically zero).
    # This retains a force-relative residual gate for tiny or large SI forces.
    momentum = max(float(np.max(np.abs(ru))),float(np.max(np.abs(rw))))
    incompressibility = float(np.max(np.abs(div)))
    meanp = float(np.mean(p))
    pressure_gauge = abs(meanp)/max(1.,float(np.max(np.abs(p))))
    multiplier = abs(float(gauge))
    weight = op.hx*op.hz
    external_work = float((np.sum(u*fx)+np.sum(w*fz))*weight)
    dissipation = op.energy(u,w)
    pressure_work = float(-np.sum(p*div)*weight)
    work_residual = abs(dissipation+pressure_work-external_work)
    work_scale = max(1.,abs(dissipation),abs(external_work),abs(pressure_work))
    net_flux = float(np.sum(div)*weight)
    d = dict(momentum_linf=momentum,divergence_linf=incompressibility,
             pressure_mean=meanp,pressure_gauge_relative=pressure_gauge,
             gauge_multiplier_abs=multiplier,net_outward_flux=net_flux,
             body_force_work=external_work,viscous_gradient_work=dissipation,
             pressure_work=pressure_work,work_balance_relative=work_residual/work_scale)
    if not all(math.isfinite(v) for v in d.values()):
        raise TectonicsError('non-finite Stokes diagnostic')
    if momentum>policy.momentum_tolerance or incompressibility>policy.divergence_tolerance:
        raise TectonicsError('Stokes momentum/divergence residual gate failed')
    if pressure_gauge>policy.gauge_tolerance or multiplier>policy.divergence_tolerance:
        raise TectonicsError('Stokes pressure gauge/compatibility gate failed')
    if d['work_balance_relative']>policy.work_balance_tolerance:
        raise TectonicsError('Stokes mechanical work balance failed')
    return d,div


class StokesSolution:
    """Immutable SI arrays plus the complete steady problem and source identity.

    Hashes bind bytes; they are not outside scientific authentication. This object
    can restore an old result without calling a present solver or rebinding its
    source. No temperature, composition history or evolving checkpoint is implied.
    """
    __slots__ = ('_metadata','_arrays','result_id')

    def __init__(self,metadata,arrays):
        if not isinstance(metadata,dict) or metadata.get('schema')!='atlas.stokes-steady-result.v1':
            raise TectonicsError('invalid Stokes result schema')
        try:
            if metadata['method']!=_METHOD or metadata['boundary']!=_BOUNDARY or metadata['gauge']!=_GAUGE:
                raise TectonicsError('unsupported Stokes result equation/boundary/gauge')
            box = StokesBox2D(**metadata['box'])
            scales = DiffusiveScales(**metadata['scales'])
            r = metadata['rheology']
            profile = RheologyProfile(r['name'],r['family'],r['source'],tuple(tuple(x) for x in r['parameters']),
                                      None if r['viscosity_bounds'] is None else tuple(r['viscosity_bounds']))
            if _json(profile.descriptor())!=_json(r):
                raise TectonicsError('Stokes profile identity mismatch')
            _scaling(box,scales,profile)
            policy = StokesSolvePolicy(**metadata['policy'])
            if metadata['physical_validation'] is not False or metadata['R4_complete'] is not False:
                raise TectonicsError('unsupported Stokes acceptance claim')
            if metadata['units']!='SI: m, s, Pa, N/m^3; Cartesian x-right, z-up':
                raise TectonicsError('unknown Stokes result units')
            for key in ('context_id','plan_id'):
                _hex(metadata[key],key)
            for key in ('forcing_source','epoch_id'):
                if not isinstance(metadata[key],str) or not metadata[key].strip() or len(metadata[key])>4096:
                    raise TectonicsError('bounded Stokes '+key+' required')
            scalar(metadata['time_s'],'snapshot time')
            scalar(metadata['force_normalisation'],'force normalisation',nonnegative=True)
            # Historical snapshots retain their original gate meaning and bytes.
            # Only new records claim the post-conversion SI publication contract.
            if 'publication_contract' in metadata:
                if metadata['publication_contract'] != 'atlas.stokes-published-si-gates.v1':
                    raise TectonicsError('unknown Stokes publication contract')
                scalar(metadata['force_amplitude_n_m3'],'SI force amplitude',nonnegative=True)
            # This is a numerical record, not permission to turn tolerance failure
            # into a pass on restore. Check the recorded gate fields as well.
            d = metadata['diagnostics']
            checks = (('momentum_linf',policy.momentum_tolerance),
                      ('divergence_linf',policy.divergence_tolerance),
                      ('pressure_gauge_relative',policy.gauge_tolerance),
                      ('gauge_multiplier_abs',policy.divergence_tolerance),
                      ('work_balance_relative',policy.work_balance_tolerance))
            for key,maximum in checks:
                if scalar(d[key],key,nonnegative=True)>maximum:
                    raise TectonicsError('recorded Stokes gate not passed')
            if type(metadata['iterations']) is not int or not 0<=metadata['iterations']<=policy.max_iterations:
                raise TectonicsError('invalid solver iteration record')
        except (KeyError,TypeError,ValueError) as exc:
            raise TectonicsError('incomplete or invalid Stokes metadata') from exc
        shapes = {'force_x_n_m3':(box.nz,box.nx-1),'force_z_n_m3':(box.nz-1,box.nx),
                  'u_m_s':(box.nz,box.nx+1),'w_m_s':(box.nz+1,box.nx),
                  'pressure_pa':(box.nz,box.nx),'divergence_s_1':(box.nz,box.nx)}
        if not isinstance(arrays,dict) or set(arrays)!=set(shapes):
            raise TectonicsError('complete Stokes arrays required')
        # Publication occurs inside a solve/restore reservation. Store raw bytes
        # and private descriptors; callers cannot mutate another reader's shape.
        data=[]
        for key,shape in sorted(shapes.items()):
            if input_shape(arrays[key],key)!=shape:
                raise TectonicsError('Stokes array shape mismatch: '+key)
            a = read_array(arrays[key],key)
            if key=='u_m_s' and (np.any(a[:,0]!=0) or np.any(a[:,-1]!=0)):
                raise TectonicsError('nonzero normal horizontal wall velocity')
            if key=='w_m_s' and (np.any(a[0]!=0) or np.any(a[-1]!=0)):
                raise TectonicsError('nonzero normal vertical wall velocity')
            data.append((key,shape,a.tobytes()))
        self._metadata = _json(metadata)
        self._arrays = tuple(data)
        h=hashlib.sha256(self._metadata)
        for name,shape,raw in data:
            h.update(_json([name,shape,'binary64'])); h.update(raw)
        self.result_id=h.hexdigest()

    def __setattr__(self,key,value):
        if hasattr(self,key):
            raise TectonicsError('Stokes result is immutable')
        object.__setattr__(self,key,value)

    def descriptor(self):
        return json.loads(self._metadata)

    @property
    def array_names(self):
        return tuple(k for k,_,_ in self._arrays)

    @property
    def nbytes(self):
        return len(self._metadata)+sum(len(b) for _,_,b in self._arrays)

    def array(self,name):
        for k,shape,b in self._arrays:
            if name==k:
                return np.frombuffer(b,dtype='f8').reshape(shape)
        raise TectonicsError('unknown Stokes array '+str(name))


class PreparedStokes2D:
    """Single-driving-thread reusable constant-viscosity box solve.

    A tiny direct reference reserves a conservative quadratic LU allowance BEFORE
    native assembly/factorisation. The default retains only O(N) spectral data;
    matrix-free MINRES uses O(N) scratch and no growing Krylov basis. Scratch and
    final publication are admitted separately. Budget admission is NOT a hard
    RSS cap: caller outputs, Python/native allocators and imported libraries need
    headroom. The explicit direct route is never an automatic fallback.
    """
    def __init__(self,box,profile,scales,*,policy=None,budget=None,cancel=None):
        if LinearOperator is None or minres is None or splu is None:
            raise TectonicsError('SciPy Stokes solvers unavailable; no backend fallback')
        scaling = _scaling(box,scales,profile)
        policy = StokesSolvePolicy() if policy is None else policy
        if type(policy) is not StokesSolvePolicy:
            raise TectonicsError('typed Stokes solve policy required')
        if box.unknowns>policy.max_unknowns:
            raise TectonicsError('Stokes unknown count exceeds requested work envelope')
        if policy.method=='direct' and box.unknowns>policy.direct_max_unknowns:
            raise TectonicsError('explicit direct-reference unknown limit exceeded')
        self.box,self.profile,self.scales,self.policy=box,profile,scales,policy
        self.budget=select_budget(budget)
        self._closed=False;self._active=False;self._lock=threading.Lock()
        self._owner=threading.get_ident();self._context=None;self._factor=None;self._inverse=None
        self._scaling=scaling
        self._op=_MACOperator(box,scaling['hx'],scaling['hz'])
        # Source snapshot allowance follows existing verified contexts. Sparse LU
        # can fill; reserve a dense-fill bound instead of guessing native fill-in.
        retained = 5*1024**2+160*box.unknowns
        if policy.method=='direct':
            retained += 64*box.unknowns**2
        self._retained_bytes=retained
        self._guard=self.budget.reserve(retained,category='stokes-plan-retained')
        self._guard.__enter__()
        try:
            _cancel(cancel)
            self._context=ExecutionContext('scipy')
            self._context_id=self._context.identity
            with _native_lease():
                self._inverse=_SeparableVelocityInverse(self._op)
                if policy.method=='direct':
                    _cancel(cancel)
                    matrix=self._op.sparse_reference()
                    self._factor=splu(matrix,permc_spec='COLAMD')
                    del matrix
            _cancel(cancel)
            self._context.verify()
            self.identity=_digest({'method':_METHOD,'box':asdict(box),'profile':profile.descriptor(),
                                   'scales':asdict(scales),'policy':asdict(policy),
                                   'boundary':_BOUNDARY,'gauge':_GAUGE,'context':self._context_id})
        except BaseException:
            self._factor=None; self._inverse=None; self._context=None; self._closed=True
            self._guard.__exit__(None,None,None)
            raise

    def __setattr__(self,name,value):
        if name in ('box','profile','scales','policy','budget','identity','_scaling','_op','_context_id') and hasattr(self,name):
            raise TectonicsError('Stokes prepared binding is immutable')
        object.__setattr__(self,name,value)

    def __enter__(self):
        if self._closed:
            raise TectonicsError('Stokes plan is closed')
        return self

    def __exit__(self,*_):
        self.close()

    @contextmanager
    def _operation(self,cancel):
        with self._lock:
            if self._closed or self._active or threading.get_ident()!=self._owner:
                raise TectonicsError('closed/active Stokes plan or wrong driving thread')
            self._active=True
        try:
            _cancel(cancel); self._context.verify()
            with _native_lease():
                yield
            _cancel(cancel); self._context.verify()
        finally:
            with self._lock:
                self._active=False

    def close(self):
        with self._lock:
            if self._closed:
                return
            if self._active or threading.get_ident()!=self._owner:
                raise TectonicsError('join Stokes solve and close on its driving thread')
            self._closed=True
        try:
            if self._context is not None:
                self._context.close()
        finally:
            self._factor=None;self._inverse=None;self._context=None
            self._guard.__exit__(None,None,None)

    @property
    def retained_bytes_estimate(self):
        return self._retained_bytes

    def solve(self,force_x_n_m3,force_z_n_m3,*,frame_id,epoch_id,time_s,source,cancel=None):
        """Solve one steady force snapshot. No motion is prescribed or time advanced.

        Required forces occupy INTERIOR u/w faces, in N/m^3. They are consumed
        exactly once; no hidden density, gravity or slab traction is added.
        time_s/epoch_id label this supplied state and never imply integration.
        """
        if frame_id!=self.box.frame_id:
            raise TectonicsError('Stokes forcing frame mismatch; explicitly transform it')
        for value,name in ((epoch_id,'epoch'),(source,'forcing provenance')):
            text(value,name)
            if len(value)>4096:
                raise TectonicsError(name+' exceeds metadata envelope')
        time_s=scalar(time_s,'forcing snapshot time')
        op=self._op
        if input_shape(force_x_n_m3)!=(op.nz,op.nx-1) or input_shape(force_z_n_m3)!=(op.nz-1,op.nx):
            raise TectonicsError('Stokes forces must match interior staggered face shapes')
        # Includes input capture, norm-scaled rhs, full MINRES vectors, FFT work,
        # independent residuals, output arrays and detached immutable publication.
        # The 768-byte/unknown allowance also covers mantissa/exponent conversion
        # buffers and reconstruction of published fields; no second solve or
        # duplicate full diagnostics is retained.
        with self._operation(cancel),self.budget.reserve(768*op.n+262144,category='stokes-solve'):
            fx=read_array(force_x_n_m3,'horizontal face force')
            fz=read_array(force_z_n_m3,'vertical face force')
            scale=self._scaling
            # Normalise the ORIGINAL force, not fx/force_scale followed by a
            # second division: the intermediate could be subnormal and distort
            # a perfectly representable SI solution. Diffusivity is an arbitrary
            # reference scale, not a parameter of this steady mechanical PDE.
            force_amplitude=max(float(np.max(np.abs(fx))),float(np.max(np.abs(fz))))
            amplitude=scalar(force_amplitude/scale['force_n_m3'],
                             'reference force normalisation',nonnegative=True)
            if force_amplitude and amplitude == 0:
                raise TectonicsError('reference force normalisation underflows')
            rhs=np.zeros(op.n)
            if force_amplitude:
                rhs[:op.nu]=_checked_scale(fx,force_amplitude,'normalised x force',divide=True).ravel()
                rhs[op.nu:op.nv]=_checked_scale(fz,force_amplitude,'normalised z force',divide=True).ravel()
            iterations=0
            def matvec(v):
                _cancel(cancel)
                return op.matvec(v)
            def inverse(v):
                _cancel(cancel)
                return self._inverse.apply(v)
            def callback(_):
                nonlocal iterations
                iterations+=1
                _cancel(cancel)
            if amplitude==0:
                vector=np.zeros(op.n)
            elif self.policy.method=='direct':
                vector=self._factor.solve(rhs)
            else:
                matrix=LinearOperator((op.n,op.n),matvec=matvec,dtype=np.float64)
                preconditioner=LinearOperator((op.n,op.n),matvec=inverse,dtype=np.float64)
                vector,info=minres(matrix,rhs,M=preconditioner,rtol=self.policy.krylov_rtol,
                                   maxiter=self.policy.max_iterations,callback=callback,check=True)
                if info!=0:
                    raise TectonicsError('Stokes MINRES did not converge within its registered iteration limit')
            _cancel(cancel)
            if not np.all(np.isfinite(vector)):
                raise TectonicsError('non-finite Stokes solution')
            u,w,p,_=op.split(vector)
            usi=np.zeros((op.nz,op.nx+1));wsi=np.zeros((op.nz+1,op.nx))
            if force_amplitude:
                length=scale['length_m']; eta=scale['viscosity_pa_s']
                # In force-normalised coordinates: U0=F L^2/eta, P0=F L.
                # Use these physical factors directly rather than multiplying
                # a rounded nondimensional amplitude by another rounded scale.
                velocity_factors=(force_amplitude,length,length)
                pressure_factors=(force_amplitude,length)
                usi[:,1:-1]=_factored_scale(u,velocity_factors,(eta,),'SI velocity')
                wsi[1:-1]=_factored_scale(w,velocity_factors,(eta,),'SI velocity')
                psi=_factored_scale(p,pressure_factors,(),'SI pressure')
                _cancel(cancel)
                # Gate the values the caller will ACTUALLY receive. Reuse the
                # private solve vector for the reconstructed normalised fields,
                # so only one independent residual/work pass is needed. This
                # catches nonzero subnormal output rounding as well as loss in
                # pressure/velocity conversion. It does not raise any tolerance.
                u[:]=_factored_scale(usi[:,1:-1],(eta,),velocity_factors,'published u normalisation')
                w[:]=_factored_scale(wsi[1:-1],(eta,),velocity_factors,'published w normalisation')
                p[:]=_factored_scale(psi,(),pressure_factors,'published pressure normalisation')
            else:
                psi=np.zeros((op.nz,op.nx))
            diagnostics,div=_diagnostics(op,vector,rhs,self.policy)
            dsi=(_factored_scale(div,(force_amplitude,scale['length_m']),
                                (scale['viscosity_pa_s'],),'SI divergence')
                 if force_amplitude else np.zeros_like(div))
            metadata={'schema':'atlas.stokes-steady-result.v1','method':_METHOD,
                      'box':asdict(self.box),'scales':asdict(self.scales),
                      'rheology':self.profile.descriptor(),'policy':asdict(self.policy),
                      'boundary':_BOUNDARY,'gauge':_GAUGE,'context_id':self._context_id,
                      'plan_id':self.identity,'forcing_source':source,'epoch_id':epoch_id,'time_s':time_s,
                      'units':'SI: m, s, Pa, N/m^3; Cartesian x-right, z-up',
                      'force_normalisation':amplitude,'iterations':iterations,
                      'force_amplitude_n_m3':force_amplitude,
                      'publication_contract':'atlas.stokes-published-si-gates.v1',
                      'diagnostic_basis':'returned SI velocity and pressure, re-expressed against original force',
                      'diagnostics':diagnostics,
                      'diagnostic_units':'force-normalised nondimensional equations; not SI heat sources',
                      'normalisation_scales':scale,
                      'state':'instantaneous mechanical response; no thermal/composition evolution',
                      'physical_validation':False,'R4_complete':False}
            arrays={'force_x_n_m3':fx,'force_z_n_m3':fz,'u_m_s':usi,'w_m_s':wsi,
                    'pressure_pa':psi,'divergence_s_1':dsi}
            return StokesSolution(metadata,arrays)


def save_stokes_solution(result,store,*,budget=None,cancel=None):
    """One existing lossless/deduplicated snapshot; never saves mutable LU factors."""
    from .storage import ArrayStore
    if type(result) is not StokesSolution or not isinstance(store,ArrayStore):
        raise TectonicsError('Stokes solution and ArrayStore required')
    _cancel(cancel)
    policy=store._budget if budget is None else budget
    with select_budget(policy).reserve(3*result.nbytes+65536,category='stokes-save'):
        return store.put(result.result_id,{k:result.array(k) for k in result.array_names},
                         result.descriptor(),budget=policy,cancel=cancel)


def load_stokes_solution(store,result_id,*,budget=None,cancel=None):
    """Restore exactly the original source-bound steady record, not evolving state."""
    from .storage import ArrayStore
    if not isinstance(store,ArrayStore):
        raise TectonicsError('ArrayStore required')
    _hex(result_id,'Stokes result')
    _cancel(cancel)
    policy=store._budget if budget is None else budget
    metadata=store.metadata(result_id)
    arrays=store.get(result_id,budget=policy)
    if arrays is None or metadata is None:
        raise TectonicsError('Stokes result not found')
    with select_budget(policy).reserve(3*sum(v.nbytes for v in arrays.values())+131072,category='stokes-restore'):
        result=StokesSolution(metadata,arrays)
        if result.result_id!=result_id:
            raise TectonicsError('Stokes snapshot identity mismatch')
        _cancel(cancel)
        return result
