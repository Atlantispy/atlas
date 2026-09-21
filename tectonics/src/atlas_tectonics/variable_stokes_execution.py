"""R4.3 prepared variable-viscosity and Picard-yielding mechanical snapshots.

SPDX-License-Identifier: AGPL-3.0-only
R4 remains IN_PROGRESS. Existing WorkBudget/ExecutionContext/native leases and
ArrayStore are reused. Two-field thermal coupling uses constant/Tosi profiles;
a BF snapshot needs explicit frozen damage and does not advect or heal it.

The true nonlinear residual is re-evaluated with the *updated* rheology, including
at the returned SI fields, not merely with the last lagged matrix. No artificial
minimum strain rate, hidden viscosity clipping, direct fallback or relaxed
convergence follows failure. The caller may select an explicit profile/policy.
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
    from scipy.sparse.linalg import LinearOperator, gmres, spilu, splu
except ImportError:
    LinearOperator = gmres = spilu = splu = None
from ._validation import TectonicsError, text, scalar, input_shape, read_array
from .resources import select_budget, MemoryLimitError
from . import anderson as _aa
from . import preconditioner_reuse as _pr
from . import adaptive_inner as _ai
from .reuse import ExecutionContext
from .constitutive import (DiffusiveScales, RheologyProfile, ConstitutiveLimits,
                           _native_law, _check_fields, _json, _cancel)
from .stokes import StokesBox2D, _BOUNDARY, _GAUGE
from .stokes_execution import _factored_scale, _checked_scale, _native_lease, _hex, _digest
from .variable_stokes import (NonlinearStokesPolicy, _StressMACOperator,
                              check_variable_support, _stress_residuals, _METHOD)


def _profile_restore(r):
    if r is None:return None
    try:
        out=RheologyProfile(r['name'],r['family'],r['source'],tuple(tuple(v) for v in r['parameters']),
                           None if r['viscosity_bounds'] is None else tuple(r['viscosity_bounds']))
        if _json(out.descriptor())!=_json(r):raise TectonicsError('rheology identity differs')
        return out
    except (KeyError,TypeError,ValueError) as exc:
        raise TectonicsError('invalid stored rheology') from exc


def _diagnostics(op,vector,rhs,policy,*,enforce=True):
    u,w,p,gauge=op.split(vector);fx,fz,_,_=op.split(rhs)
    ru,rw,div,dissipation=_stress_residuals(op,u,w,p,fx,fz)
    external=float((np.sum(u*fx)+np.sum(w*fz))*op.hx*op.hz)
    pressure_work=float(-np.sum(p*div)*op.hx*op.hz)
    d=dict(momentum_linf=max(float(np.max(np.abs(ru))),float(np.max(np.abs(rw)))),
           divergence_linf=float(np.max(np.abs(div))),
           pressure_gauge_relative=abs(float(np.mean(p)))/max(1.,float(np.max(np.abs(p)))),
           gauge_multiplier_abs=abs(float(gauge)),body_force_work=external,
           viscous_stress_work=dissipation,pressure_work=pressure_work,
           work_balance_relative=abs(dissipation+pressure_work-external)/max(1.,abs(dissipation),abs(external),abs(pressure_work)))
    if not all(math.isfinite(v) for v in d.values()):raise TectonicsError('nonfinite variable-mechanics diagnostic')
    if enforce:_check_diagnostics(d,policy)
    return d,div


def _check_diagnostics(d,policy):
    for key,limit in (('momentum_linf',policy.momentum_tolerance),
                      ('divergence_linf',policy.divergence_tolerance),
                      ('pressure_gauge_relative',policy.gauge_tolerance),
                      ('gauge_multiplier_abs',policy.divergence_tolerance),
                      ('work_balance_relative',policy.work_balance_tolerance)):
        if not 0<=d[key]<=limit:
            raise TectonicsError('variable Stokes '+key+' gate failed: '+str(d[key]))


class VariableStokesSolution:
    """Immutable complete mechanical input/response; not a time-integrated state."""
    __slots__=('_metadata','_arrays','result_id')
    def __init__(self,metadata,arrays):
        try:
            if metadata['schema']!='atlas.variable-stokes-result.v1' or metadata['method']!=_METHOD:
                raise TectonicsError('unsupported variable mechanical record')
            b=StokesBox2D(**metadata['box']);sc=DiffusiveScales(**metadata['scales'])
            check_variable_support(b,sc);pol=NonlinearStokesPolicy(**metadata['policy'])
            if _json(asdict(pol))!=_json(metadata['policy']):raise TectonicsError('noncanonical nonlinear policy')
            rp=_profile_restore(metadata['rheology'])
            if metadata['mode'] not in ('prescribed-viscosity','rheology') or (rp is None)!=(metadata['mode']=='prescribed-viscosity'):
                raise TectonicsError('inconsistent mechanical input mode')
            if metadata['boundary']!=_BOUNDARY or metadata['gauge']!=_GAUGE:
                raise TectonicsError('unsupported variable mechanical boundary')
            if metadata['R4_status']!='IN_PROGRESS' or metadata['physical_validation'] is not False:
                raise TectonicsError('unsupported physical acceptance claim')
            if metadata['units']!='SI: m, s, Pa, Pa s, N/m^3; x-right z-up':
                raise TectonicsError('unknown units')
            for k in ('context_id','plan_id'):_hex(metadata[k],k)
            for k in ('source','epoch_id'):text(metadata[k],k)
            scalar(metadata['time_s'],'time');scalar(metadata['force_amplitude_n_m3'],'force amplitude',nonnegative=True)
            scalar(metadata['viscosity_reference_pa_s'],'viscosity reference',positive=True)
            _check_diagnostics(metadata['diagnostics'],pol)
            if metadata['publication_contract']!='true-rheology-returned-si-v1':raise TectonicsError('unsupported publication')
            hist=metadata['nonlinear_history']
            if type(hist) is not list or not 1<=len(hist)<=pol.max_picard_iterations:
                raise TectonicsError('invalid nonlinear history')
            for row in hist:
                for k in ('momentum_linf','viscosity_log_change'):
                    scalar(row[k],k,nonnegative=True)
                if type(row['linear_iterations']) is not int or not 0<=row['linear_iterations']<=pol.restart*pol.max_cycles:
                    raise TectonicsError('invalid linear iteration count')
            if 'adaptive_inner' in metadata:
                if rp is None or rp.family not in ('constant','tosi-linear','tosi-plastic'):
                    raise TectonicsError('adaptive inner supports constant/Tosi only')
                if metadata['adaptive_inner']['active'] != (rp.family == 'tosi-plastic'):
                    raise TectonicsError('adaptive activation differs from rheology')
                _ai.check_history(metadata['adaptive_inner'],metadata['adaptive_inner_history'],hist,pol)
            elif 'adaptive_inner_history' in metadata:
                raise TectonicsError('undeclared adaptive-inner history')
            if 'preconditioner_reuse' in metadata:
                if rp is None or rp.family not in ('constant','tosi-linear','tosi-plastic'):
                    raise TectonicsError('unsupported preconditioner-reuse rheology')
                if metadata['preconditioner_reuse']['active']!=(rp.family=='tosi-plastic'):
                    raise TectonicsError('preconditioner activation differs from rheology')
                _pr.check_history(metadata['preconditioner_reuse'],metadata['preconditioner_history'],hist,pol)
            elif 'preconditioner_history' in metadata:
                raise TectonicsError('undeclared preconditioner history')
            if 'nonlinear_acceleration' in metadata:
                if rp is None or rp.family not in ('constant','tosi-linear','tosi-plastic'):
                    raise TectonicsError('Anderson supports constant/Tosi rheology only')
                ap=_aa.check_summary(metadata['nonlinear_acceleration'],len(hist))
                _aa.check_policy(ap,pol)
                _aa.check_history(hist,metadata['nonlinear_acceleration'])
            elif any('anderson' in row for row in hist):
                raise TectonicsError('undeclared Anderson iteration history')
            if hist[-1]['momentum_linf']>pol.momentum_tolerance or hist[-1]['viscosity_log_change']>pol.viscosity_rtol:
                raise TectonicsError('nonlinear record is unconverged')
        except (KeyError,TypeError,ValueError) as exc:
            raise TectonicsError('invalid variable mechanical metadata') from exc
        guess_record=metadata.get('initial_guess')
        if 'initial_guess' in metadata:
            if rp is None or rp.family=='bf23-memory':
                raise TectonicsError('initial guesses support constant/Tosi rheology only')
            if type(guess_record) is not dict or set(guess_record)!={'guess_id','descriptor'}:
                raise TectonicsError('invalid recorded initial guess')
            try:
                guess=NonlinearStokesGuess.restore(guess_record['descriptor'],
                    {k:arrays['initial_guess_'+k] for k in ('u_m_s','w_m_s','pressure_pa')},
                    guess_record['guess_id'])
            except (KeyError,TypeError,ValueError) as exc:
                raise TectonicsError('invalid recorded initial-guess fields') from exc
            _check_guess_binding(guess,metadata['plan_id'],rp,metadata['epoch_id'],metadata['time_s'],box=b,scales=sc)
        shape=(b.nz,b.nx);vertex=(b.nz-1,b.nx-1)
        shapes={'force_x_n_m3':(b.nz,b.nx-1),'force_z_n_m3':(b.nz-1,b.nx),
                'u_m_s':(b.nz,b.nx+1),'w_m_s':(b.nz+1,b.nx),'pressure_pa':shape,
                'divergence_s_1':shape,'viscosity_cell_pa_s':shape,'viscosity_vertex_pa_s':vertex,
                'strain_rate_cell_s_1':shape,'strain_rate_vertex_s_1':vertex}
        if rp is not None:
            shapes.update(temperature_k=shape,clipped_cell=shape,clipped_vertex=vertex)
            if rp.family=='bf23-memory':shapes['frozen_damage']=shape
        if guess_record is not None:
            shapes.update(initial_guess_u_m_s=(b.nz,b.nx+1),
                          initial_guess_w_m_s=(b.nz+1,b.nx),initial_guess_pressure_pa=shape)
        if type(arrays) is not dict or set(arrays)!=set(shapes):raise TectonicsError('complete mechanical arrays required')
        data=[]
        for k,s in sorted(shapes.items()):
            if input_shape(arrays[k])!=s:raise TectonicsError('variable mechanical array shape: '+k)
            a=read_array(arrays[k],k)
            if k.startswith('viscosity') and np.any(a<=0):raise TectonicsError('nonpositive stored viscosity')
            if k.startswith('strain_rate') and np.any(a<0):raise TectonicsError('negative invariant')
            if k.startswith('clipped') and not np.isin(a,(0,1,2)).all():raise TectonicsError('invalid clipping mask')
            if k=='u_m_s' and np.any(a[:,[0,-1]]):raise TectonicsError('nonzero normal wall velocity')
            if k=='w_m_s' and np.any(a[[0,-1]]):raise TectonicsError('nonzero normal wall velocity')
            if k=='frozen_damage' and np.any(a<0):raise TectonicsError('negative frozen damage')
            data.append((k,s,a.tobytes()))
        raw=_json(metadata)
        if len(raw)>4*1024**2:raise TectonicsError('mechanical metadata exceeds envelope')
        self._metadata=raw;self._arrays=tuple(data)
        h=hashlib.sha256(raw)
        for k,s,v in data:h.update(_json([k,s,'binary64']));h.update(v)
        self.result_id=h.hexdigest()
    def __setattr__(self,k,v):
        if hasattr(self,k):raise TectonicsError('mechanical result immutable')
        object.__setattr__(self,k,v)
    def descriptor(self):return json.loads(self._metadata)
    @property
    def array_names(self):return tuple(k for k,_,_ in self._arrays)
    @property
    def nbytes(self):return len(self._metadata)+sum(len(v) for _,_,v in self._arrays)
    def array(self,key):
        for k,s,v in self._arrays:
            if k==key:return np.frombuffer(v,dtype='f8').reshape(s)
        raise TectonicsError('unknown variable mechanical array')


class NonlinearStokesGuess:
    """Explicit immutable SI starting fields, not an accepted answer to a new solve.

    Capture only velocity and pressure, not a recursive chain of earlier results.
    Source/plan, rheology, geometry, epoch and time bindings remain explicit.
    Recorded guesses restore without the original solution or an earlier store.
    Caller-retained instances need headroom outside the prepared solver budget.
    """
    __slots__=('_metadata','_arrays','guess_id')

    def __init__(self,solution,*,budget=None):
        if type(solution) is not VariableStokesSolution:
            raise TectonicsError('initial guess requires a typed mechanical solution')
        m=solution.descriptor()
        if m['mode']!='rheology' or m['rheology']['family']=='bf23-memory':
            raise TectonicsError('initial guesses support constant/Tosi rheology only')
        meta=dict(schema='atlas.nonlinear-stokes-guess.v1',box=m['box'],scales=m['scales'],
                  rheology=m['rheology'],plan_id=m['plan_id'],epoch_id=m['epoch_id'],
                  time_s=m['time_s'],source_result_id=solution.result_id)
        self._capture(meta,{k:solution.array(k) for k in ('u_m_s','w_m_s','pressure_pa')},budget)

    def _capture(self,meta,arrays,budget):
        try:
            keys={'schema','box','scales','rheology','plan_id','epoch_id','time_s','source_result_id'}
            if type(meta) is not dict or set(meta)!=keys or meta['schema']!='atlas.nonlinear-stokes-guess.v1':
                raise TectonicsError('invalid initial-guess descriptor')
            b=StokesBox2D(**meta['box']);sc=DiffusiveScales(**meta['scales'])
            check_variable_support(b,sc)
            rp=_profile_restore(meta['rheology'])
            if rp is None or rp.family=='bf23-memory':
                raise TectonicsError('initial guesses support constant/Tosi rheology only')
            for k in ('plan_id','source_result_id'):_hex(meta[k],k)
            text(meta['epoch_id'],'initial-guess epoch');scalar(meta['time_s'],'initial-guess time')
            if (len(meta['epoch_id'])>4096 or _json(asdict(b))!=_json(meta['box']) or
                    _json(asdict(sc))!=_json(meta['scales'])):
                raise TectonicsError('noncanonical initial-guess geometry/scales')
            shapes={'u_m_s':(b.nz,b.nx+1),'w_m_s':(b.nz+1,b.nx),'pressure_pa':(b.nz,b.nx)}
            if type(arrays) is not dict or set(arrays)!=set(shapes):
                raise TectonicsError('complete initial-guess fields required')
            if any(input_shape(arrays[k])!=shape for k,shape in shapes.items()):
                raise TectonicsError('initial-guess field shape differs')
            with select_budget(budget).reserve(64*b.nx*b.nz+131072,category='nonlinear-stokes-guess'):
                data=[]
                for k,shape in sorted(shapes.items()):
                    a=read_array(arrays[k],k)
                    if ((k=='u_m_s' and np.any(a[:,[0,-1]])) or
                            (k=='w_m_s' and np.any(a[[0,-1]]))):
                        raise TectonicsError('initial guess violates normal wall boundary')
                    data.append((k,shape,a.tobytes()))
                raw=_json(meta)
                if len(raw)>65536:raise TectonicsError('oversized initial-guess metadata')
                h=hashlib.sha256(raw)
                for k,shape,v in data:h.update(_json([k,shape,'binary64']));h.update(v)
                self._metadata=raw;self._arrays=tuple(data);self.guess_id=h.hexdigest()
        except MemoryLimitError:
            raise
        except (KeyError,TypeError,ValueError) as exc:
            raise TectonicsError('invalid nonlinear initial guess') from exc

    def __setattr__(self,k,v):
        if hasattr(self,k):raise TectonicsError('initial guess is immutable')
        object.__setattr__(self,k,v)

    def descriptor(self):return json.loads(self._metadata)

    @property
    def nbytes(self):return len(self._metadata)+sum(len(v) for _,_,v in self._arrays)

    def array(self,key):
        for k,shape,v in self._arrays:
            if k==key:return np.frombuffer(v,dtype='f8').reshape(shape)
        raise TectonicsError('unknown initial-guess field')

    @classmethod
    def restore(cls,metadata,arrays,guess_id,*,budget=None):
        _hex(guess_id,'initial guess')
        out=object.__new__(cls);out._capture(metadata,arrays,budget)
        if out.guess_id!=guess_id:raise TectonicsError('initial-guess identity differs')
        return out


def _check_guess_binding(guess,plan_id,profile,epoch,time,*,box,scales):
    if type(guess) is not NonlinearStokesGuess:
        raise TectonicsError('typed explicit nonlinear initial guess required')
    m=guess.descriptor()
    if m['plan_id']!=plan_id or _json(m['box'])!=_json(asdict(box)) or _json(m['scales'])!=_json(asdict(scales)):
        raise TectonicsError('initial-guess source/plan/geometry/scales/policy differs')
    if _json(m['rheology'])!=_json(profile.descriptor()):
        raise TectonicsError('initial-guess rheology differs')
    if m['epoch_id']!=epoch or m['time_s']>time:
        raise TectonicsError('initial-guess epoch/time is incompatible')


class PreparedVariableStokes2D:
    """One driving thread, reusable sparse derivatives and one numerical factor.

    Native sparse velocity ILU supplies a block-triangular GMRES preconditioner.
    Pressure uses a projected viscosity-weighted inverse Schur approximation.
    It is approximate and contrast-sensitive, NOT the exact constant-eta FFT
    inverse. Fixed coefficients reuse one factor; changed eta replaces it. No
    factor, source verification or accuracy gate is carried stale across a call.
    """
    def __init__(self,box,scales,*,policy=None,anderson_policy=None,preconditioner_reuse_policy=None,adaptive_inner_policy=None,budget=None,cancel=None):
        hx,hz=check_variable_support(box,scales)
        if gmres is None or spilu is None:raise TectonicsError('SciPy variable mechanics unavailable')
        policy=NonlinearStokesPolicy() if policy is None else policy
        if type(policy) is not NonlinearStokesPolicy:raise TectonicsError('typed nonlinear solve policy required')
        if box.unknowns>policy.max_unknowns:raise TectonicsError('variable mechanics exceeds unknown envelope')
        if policy.method=='direct' and box.unknowns>policy.direct_max_unknowns:
            raise TectonicsError('direct variable reference exceeds envelope')
        if anderson_policy is not None:_aa.check_policy(anderson_policy,policy)
        if preconditioner_reuse_policy is not None:_pr.check_policy(preconditioner_reuse_policy,policy)
        if adaptive_inner_policy is not None:_ai.check_policy(adaptive_inner_policy,policy)
        self.adaptive_inner_policy=adaptive_inner_policy
        self._adaptive_request=None
        self.preconditioner_reuse_policy=preconditioner_reuse_policy
        self._reuse_request=None
        self._approximate_reuses=0
        self.anderson_policy=anderson_policy
        self.box,self.scales,self.policy=box,scales,policy
        self.budget=select_budget(budget);self._closed=False;self._active=False;self._owner=threading.get_ident()
        self._context=None;self._op=None;self._factor=None;self._factor_key=None;self._factor_builds=0;self._factor_reuses=0
        # Sparse derivatives, two overlapping factor lifetimes during replacement,
        # native fill/workspace and captured source. fill_factor is a solver hint,
        # not a hard allocator cap; generous admission remains an estimate.
        # GMRES retains a geometry-only velocity-block template (<=768 B/cell).
        # Its one-time symbolic construction has a separate conservative transient
        # allowance. The explicit direct reference keeps predecessor sparse assembly.
        compiled=policy.method=='gmres'
        template_retained=(768*box.nx*box.nz+8) if compiled else 0
        template_build=(4096*box.nx*box.nz+65536) if compiled else 0
        retained=6*1024**2+template_retained+int((640+640*policy.ilu_fill_factor)*box.unknowns)
        if policy.method=='direct':retained+=64*box.unknowns**2
        self._guard=self.budget.reserve(retained,category='variable-stokes-retained');self._guard.__enter__()
        self._retained=retained
        try:
            _cancel(cancel)
            if compiled:
                with self.budget.reserve(template_build,category='variable-stokes-template-build'):
                    self._op=_StressMACOperator(box,hx,hz,compiled=True)
                if self._op.velocity_template_nbytes>template_retained:
                    raise TectonicsError('velocity template exceeds admitted retained estimate')
            else:self._op=_StressMACOperator(box,hx,hz,compiled=False)
            self._context=ExecutionContext('numba' if compiled else 'scipy');self._context_id=self._context.identity
            binding=dict(method=_METHOD,box=asdict(box),scales=asdict(scales),
                         policy=asdict(policy),context=self._context_id)
            if anderson_policy is not None:binding['anderson_policy']=asdict(anderson_policy)
            if preconditioner_reuse_policy is not None:binding['preconditioner_reuse_policy']=asdict(preconditioner_reuse_policy)
            if adaptive_inner_policy is not None:binding['adaptive_inner_policy']=asdict(adaptive_inner_policy)
            self.identity=_digest(binding)
            _cancel(cancel)
        except BaseException:
            self._op=None;self._context=None;self._closed=True;self._guard.__exit__(None,None,None)
            raise
    def __setattr__(self,k,v):
        if k in ('box','scales','policy','anderson_policy','preconditioner_reuse_policy','adaptive_inner_policy','budget','identity','_context_id') and hasattr(self,k):
            raise TectonicsError('variable mechanics binding immutable')
        object.__setattr__(self,k,v)
    def __enter__(self):
        if self._closed:raise TectonicsError('variable mechanics closed')
        return self
    def __exit__(self,*_):self.close()
    @contextmanager
    def _operation(self,cancel):
        if self._closed or self._active or self._owner!=threading.get_ident():
            raise TectonicsError('closed/active variable plan or wrong driving thread')
        self._active=True
        try:
            _cancel(cancel);self._context.verify()
            with _native_lease():yield
            _cancel(cancel);self._context.verify()
        finally:self._active=False
    def close(self):
        if self._closed:return
        if self._active or self._owner!=threading.get_ident():raise TectonicsError('close idle variable plan on driving thread')
        self._closed=True
        try:
            if self._context is not None:self._context.close()
        finally:
            self._context=None;self._op=None;self._factor=None;self._factor_key=None
            self._guard.__exit__(None,None,None)
    def statistics(self):
        return dict(factor_builds=self._factor_builds,factor_reuses=self._factor_reuses,retained_admitted_bytes=self._retained, approximate_factor_reuses=self._approximate_reuses)

    def _coefficients(self,c,v):
        if not np.isfinite(c).all() or not np.isfinite(v).all() or min(c.min(),v.min())<=0:
            raise TectonicsError('finite positive viscosity required')
        lo=min(float(c.min()),float(v.min()));hi=max(float(c.max()),float(v.max()))
        if math.log(hi)-math.log(lo)>math.log(self.policy.max_viscosity_contrast)+8*np.finfo(float).eps:
            raise TectonicsError('viscosity contrast exceeds declared solve envelope')
        self._op.set_viscosity(c,v)

    @contextmanager
    def _preconditioner_request(self,profile):
        # Bypass known strain-independent laws without allocating history/maps.
        if self.preconditioner_reuse_policy is None or profile.family!='tosi-plastic':
            yield
            return
        extra=_pr.request_bytes(self.box.nx*self.box.nz,self.policy.max_picard_iterations)
        with self.budget.reserve(extra,category='preconditioner-reuse-request'):
            self._reuse_request=_pr._Request(self.preconditioner_reuse_policy)
            try:yield
            finally:self._reuse_request=None

    @contextmanager
    def _adaptive_operation(self,profile):
        if self.adaptive_inner_policy is None or profile.family != 'tosi-plastic':
            yield
            return
        extra=_ai.request_bytes(self.box.unknowns,self.policy.max_picard_iterations)
        with self.budget.reserve(extra,category='adaptive-inner-request'):
            self._adaptive_request=_ai._Request(self.adaptive_inner_policy)
            try:yield
            finally:self._adaptive_request=None

    def _adaptive_linear(self,rhs,guess,cancel):
        """Provisional correction; only a strict, freshly checked image can publish.

        The absolute target uses the original RHS norm. There is deliberately no
        round-off enlargement of the strict target and no failed-solve retry.
        """
        op=self._op;pol=self.policy;request=self._adaptive_request
        x0=np.zeros(op.n) if guess is None else np.asarray(guess,dtype=np.float64)
        _cancel(cancel)
        defect=rhs-op.matvec(x0)
        norm_b=float(np.linalg.norm(rhs));norm_d=float(np.linalg.norm(defect))
        if not math.isfinite(norm_b) or not math.isfinite(norm_d):
            raise TectonicsError('nonfinite adaptive linear defect')
        forced=request.strict_phase
        target,strict=_ai.target(request.policy,pol.linear_rtol,norm_b,norm_d,forced)
        reset=bool(strict and not request.has_strict)
        if strict:request.strict_phase=True;request.has_strict=True
        count=0
        if np.any(rhs):
            self._factorise(cancel)
            def matvec(x):_cancel(cancel);return op.matvec(x)
            def precondition(x):
                _cancel(cancel)
                _,_,r,g=op.split(x)
                mean=float(np.mean(r));p=-2*op.eta_c*(r-mean)
                p-=np.mean(p);p+=op.c*g
                vu=self._factor.solve(x[:op.nv]-op.g@p.ravel())
                return np.concatenate((vu,p.ravel(),[mean/op.c]))
            def iteration(_):
                nonlocal count
                count+=1;_cancel(cancel)
            a=LinearOperator((op.n,op.n),matvec=matvec,dtype=np.float64)
            m=LinearOperator((op.n,op.n),matvec=precondition,dtype=np.float64)
            delta,info=gmres(a,defect,M=m,rtol=0.,atol=target,
                restart=pol.restart,maxiter=pol.max_cycles,
                callback=iteration,callback_type='pr_norm')
            if info!=0:raise TectonicsError('adaptive correction GMRES failed; no retry')
            vector=x0+delta
        else:
            vector=np.zeros(op.n)
        _cancel(cancel)
        residual=float(np.linalg.norm(rhs-op.matvec(vector)))
        if not np.isfinite(vector).all() or not math.isfinite(residual) or residual>target:
            raise TectonicsError('adaptive correction failed its true linear target')
        # Provisional images are internal only. Do not enforce final physical
        # gates against an intentionally loose intermediate linear solution.
        _diagnostics(op,vector,rhs,pol,enforce=strict)
        request.rows.append(dict(rhs_l2=norm_b,defect_l2=norm_d,target_l2=target,
            residual_l2=residual,strict_requested=forced,strict_certified=strict,
            history_reset=reset,iterations=count))
        if strict:
            request.cert_c=op.eta_c.copy();request.cert_v=op.eta_v.copy()
            request.coefficient_hash=_pr.coefficient_key(op)
        return vector,count

    def _certify_adaptive_publication(self,vector,rhs,cancel):
        """Recheck the strict linear system after SI round-trip, before new-law checks."""
        request=self._adaptive_request
        if request is None:return
        if not request.rows or not request.rows[-1]['strict_certified']:
            raise TectonicsError('provisional adaptive result cannot be published')
        _cancel(cancel)
        self._coefficients(request.cert_c,request.cert_v)
        residual=float(np.linalg.norm(rhs-self._op.matvec(vector)))
        target=self.policy.linear_rtol*float(np.linalg.norm(rhs))
        if not math.isfinite(residual) or residual>target:
            raise TectonicsError('returned fields fail strict linear certification')
        request.returned_residual=residual

    def _factorise(self,cancel):
        _cancel(cancel)
        reuse=self._reuse_request
        if reuse is None:
            return self._factorise_current(cancel)
        decision=reuse.decision(self._op,self._factor_key)
        if decision[0]=='bounded_reuse':
            if self._factor is None:raise TectonicsError('absent factor cannot be reused')
            self._approximate_reuses+=1
        else:self._factorise_current(cancel)
        reuse.selected(self._op,self._factor_key,decision)
        _cancel(cancel)

    def _factorise_current(self,cancel):
        op=self._op;key=hashlib.sha256(op.eta_c.tobytes()+op.eta_v.tobytes()).hexdigest()
        if self._factor_key==key:
            self._factor_reuses+=1;return
        _cancel(cancel)
        try:
            if self.policy.method=='direct':factor=splu(op.sparse_reference(),permc_spec='COLAMD')
            else:
                factor=spilu(op.velocity_matrix(),drop_tol=self.policy.ilu_drop_tolerance,
                             fill_factor=self.policy.ilu_fill_factor,permc_spec='COLAMD')
        except RuntimeError as exc:raise TectonicsError('variable viscosity factorisation failed; no direct fallback') from exc
        _cancel(cancel)
        self._factor=factor;self._factor_key=key;self._factor_builds+=1

    def _linear(self,rhs,guess,cancel):
        if self._reuse_request is None:
            return self._linear_impl(rhs,guess,cancel)
        self._reuse_request.pending=None
        vector,count=self._linear_impl(rhs,guess,cancel)
        self._reuse_request.complete(self._op,count)
        return vector,count

    def _linear_impl(self,rhs,guess,cancel):
        if self._adaptive_request is not None:return self._adaptive_linear(rhs,guess,cancel)
        op=self._op;pol=self.policy
        if not np.any(rhs):return np.zeros(op.n),0
        self._factorise(cancel)
        if pol.method=='direct':return self._factor.solve(rhs),0
        def matvec(x):_cancel(cancel);return op.matvec(x)
        def precondition(x):
            _cancel(cancel)
            _,_,r,g=op.split(x)
            # Pressure mean/gauge pair is handled exactly. The projected local
            # inverse approximates the Schur complement on mean-zero pressure.
            mean=float(np.mean(r));p=-2*op.eta_c*(r-mean)
            p-=np.mean(p);p+=op.c*g
            vu=self._factor.solve(x[:op.nv]-op.g@p.ravel())
            return np.concatenate((vu,p.ravel(),[mean/op.c]))
        count=0
        def iteration(_):
            nonlocal count
            count+=1;_cancel(cancel)
        a=LinearOperator((op.n,op.n),matvec=matvec,dtype=np.float64)
        m=LinearOperator((op.n,op.n),matvec=precondition,dtype=np.float64)
        x,info=gmres(a,rhs,x0=guess,M=m,rtol=pol.linear_rtol,atol=0.,restart=pol.restart,
                     maxiter=pol.max_cycles,callback=iteration,callback_type='pr_norm')
        if info!=0:raise TectonicsError('variable Stokes GMRES failed within its fixed iteration envelope')
        _cancel(cancel)
        if not np.isfinite(x).all():raise TectonicsError('nonfinite variable solution')
        # Lagged linear solve gate cannot be mistaken for nonlinear acceptance.
        _diagnostics(op,x,rhs,pol)
        return x,count

    def _inputs(self,fx,fz,frame,epoch,time,source):
        op=self._op
        if frame!=self.box.frame_id:raise TectonicsError('variable forcing frame mismatch')
        for x,n in ((epoch,'epoch'),(source,'source')):
            text(x,n)
            if len(x)>4096:raise TectonicsError('oversized '+n)
        scalar(time,'mechanical time')
        if input_shape(fx)!=(op.nz,op.nx-1) or input_shape(fz)!=(op.nz-1,op.nx):
            raise TectonicsError('variable mechanical forcing shapes differ')
        fx=read_array(fx,'x force');fz=read_array(fz,'z force')
        F=max(float(np.max(np.abs(fx))),float(np.max(np.abs(fz))))
        rhs=np.zeros(op.n)
        if F:
            rhs[:op.nu]=_checked_scale(fx,F,'x force normalisation',divide=True).ravel()
            rhs[op.nu:op.nv]=_checked_scale(fz,F,'z force normalisation',divide=True).ravel()
        return fx,fz,F,rhs

    def solve(self,force_x_n_m3,force_z_n_m3,viscosity_cell_pa_s,viscosity_vertex_pa_s,*,
              frame_id,epoch_id,time_s,source,cancel=None):
        """Prescribed viscosity at centres AND interior vertices, no hidden averaging."""
        if self.adaptive_inner_policy is not None:
            raise TectonicsError('adaptive inner is unused for prescribed viscosity')
        if self.anderson_policy is not None:
            raise TectonicsError('Anderson policy is unused for prescribed viscosity; select a Picard plan')
        if self.preconditioner_reuse_policy is not None:
            raise TectonicsError('preconditioner reuse is unused for prescribed viscosity')
        time_s=scalar(time_s,'mechanical time')
        op=self._op
        if self._closed:raise TectonicsError('variable plan closed')
        if input_shape(viscosity_cell_pa_s)!=(op.nz,op.nx) or input_shape(viscosity_vertex_pa_s)!=(op.nz-1,op.nx-1):
            raise TectonicsError('viscosity stress-site shapes differ')
        with self._operation(cancel),self.budget.reserve(self._scratch_bytes(),category='variable-stokes-solve'):
            fx,fz,F,rhs=self._inputs(force_x_n_m3,force_z_n_m3,frame_id,epoch_id,time_s,source)
            c=read_array(viscosity_cell_pa_s,'cell viscosity')
            v=read_array(viscosity_vertex_pa_s,'vertex viscosity')
            if np.any(c<=0) or np.any(v<=0):raise TectonicsError('viscosities must be positive')
            # Balance coefficients without selecting a new physical viscosity.
            eta=math.exp(.5*(math.log(min(c.min(),v.min()))+math.log(max(c.max(),v.max()))))
            ec=_checked_scale(c,eta,'cell viscosity scale',divide=True)
            ev=_checked_scale(v,eta,'vertex viscosity scale',divide=True)
            self._coefficients(ec,ev)
            vec,it=self._linear(rhs,None,cancel)
            d,_=_diagnostics(op,vec,rhs,self.policy)
            history=[dict(momentum_linf=d['momentum_linf'],viscosity_log_change=0.,linear_iterations=it)]
            return self._publish(vec,rhs,fx,fz,F,eta,None,None,None,history,epoch_id,time_s,source,cancel)

    def _scratch_bytes(self):
        # Bounded GMRES basis, numeric A/ILU replacement (retained allowance),
        # lagged/new viscosities, tensor reconstruction, output copies and checks.
        return (1200+16*self.policy.restart)*self.box.unknowns+524288

    def solve_rheology(self,force_x_n_m3,force_z_n_m3,temperature_k,profile,*,
                       frame_id,epoch_id,time_s,source,frozen_damage=None,initial_guess=None,cancel=None):
        """Solve the retained local law, not merely freeze eta from a guessed rate.

        T is cell-centred; interior-vertex T is its four-cell arithmetic mean.
        Depth is measured DOWN from the box top and divided by the named R3
        depth scale. Dynamic pressure is never an absolute-pressure law input.
        BF damage, when requested, is an explicit fixed snapshot; no time evolves.
        By default every request starts at zero rate. An explicit constant/Tosi
        guess is rescaled from SI to THIS force/reference and evaluated with THIS
        temperature. No viscosity, factor, accepted solution or convergence gate
        is borrowed from the seed. Zero current forcing uses the exact zero start.
        """
        time_s=scalar(time_s,'mechanical time')
        if type(profile) is not RheologyProfile:raise TectonicsError('typed R3 rheology required')
        if self.adaptive_inner_policy is not None and profile.family not in ('constant','tosi-linear','tosi-plastic'):
            raise TectonicsError('adaptive inner supports constant/Tosi only')
        if self.preconditioner_reuse_policy is not None and profile.family not in ('constant','tosi-linear','tosi-plastic'):
            raise TectonicsError('preconditioner reuse supports constant/Tosi only')
        if self.anderson_policy is not None and profile.family not in ('constant','tosi-linear','tosi-plastic'):
            raise TectonicsError('Anderson supports constant/Tosi only; frozen damage remains Picard')
        b=self.box;shape=(b.nz,b.nx)
        if input_shape(temperature_k)!=shape:raise TectonicsError('temperature shape differs')
        if b.height_m>self.scales.depth_scale_m:raise TectonicsError('box exceeds depth normalisation')
        if (profile.family=='bf23-memory') != (frozen_damage is not None):
            raise TectonicsError('explicit frozen damage is required only for BF snapshots')
        if frozen_damage is not None and input_shape(frozen_damage)!=shape:raise TectonicsError('frozen damage shape differs')
        if initial_guess is not None:
            if profile.family=='bf23-memory':raise TectonicsError('BF warm starts are outside this increment')
            _check_guess_binding(initial_guess,self.identity,profile,epoch_id,time_s,box=self.box,scales=self.scales)
        extra=0 if initial_guess is None else 8*initial_guess.nbytes+131072
        with self._operation(cancel),self.budget.reserve(self._scratch_bytes()+extra,category='variable-stokes-solve'),self._preconditioner_request(profile),self._adaptive_operation(profile):
            fx,fz,F,rhs=self._inputs(force_x_n_m3,force_z_n_m3,frame_id,epoch_id,time_s,source)
            T=read_array(temperature_k,'temperature');damage=None if frozen_damage is None else read_array(frozen_damage,'damage',nonnegative=True)
            eta=self.scales.viscosity_pa_s
            law=self._law_inputs(T,damage)
            vector=np.zeros(self._op.n)
            if initial_guess is not None and F:
                u,w,p,_=self._op.split(vector);L=self.scales.length_m
                u[:]=_factored_scale(initial_guess.array('u_m_s')[:,1:-1],(eta,),(F,L,L),'initial u normalisation')
                w[:]=_factored_scale(initial_guess.array('w_m_s')[1:-1],(eta,),(F,L,L),'initial w normalisation')
                p[:]=_factored_scale(initial_guess.array('pressure_pa'),(),(F,L),'initial p normalisation')
            ec,ev,_,_=self._law(vector,F,eta,profile,law)
            if self.anderson_policy is not None:
                with self.budget.reserve(_aa.history_bytes(self._op.n,self.anderson_policy),
                                         category='anderson-history'):
                    return self._anderson_solve(vector,ec,ev,rhs,fx,fz,F,eta,profile,T,law,
                                                epoch_id,time_s,source,cancel,initial_guess)
            history=[]
            for _ in range(self.policy.max_picard_iterations):
                _cancel(cancel);self._coefficients(ec,ev)
                candidate,it=self._linear(rhs,vector,cancel)
                if self.policy.relaxation!=1.:
                    candidate=vector+self.policy.relaxation*(candidate-vector)
                nc,nv,_,_=self._law(candidate,F,eta,profile,law)
                change=max(float(np.max(np.abs(np.log(nc)-np.log(ec)))),float(np.max(np.abs(np.log(nv)-np.log(ev)))))
                self._coefficients(nc,nv)
                d,_=_diagnostics(self._op,candidate,rhs,self.policy,enforce=False)
                history.append(dict(momentum_linf=d['momentum_linf'],viscosity_log_change=change,linear_iterations=it))
                vector=candidate;ec,ev=nc,nv
                if (d['momentum_linf']<=self.policy.momentum_tolerance and change<=self.policy.viscosity_rtol):
                    if self._adaptive_request is not None and not self._adaptive_request.rows[-1]['strict_certified']:
                        self._adaptive_request.strict_phase=True
                        continue
                    _check_diagnostics(d,self.policy)
                    return self._publish(vector,rhs,fx,fz,F,eta,profile,T,damage,history,epoch_id,time_s,source,cancel,initial_guess=initial_guess)
            raise TectonicsError('nonlinear rheology failed within fixed Picard envelope; no endpoint published; residual='+str(history[-1]['momentum_linf']))


    def _anderson_solve(self,vector,ec,ev,rhs,fx,fz,F,eta,profile,T,law,
                        epoch,time,source,cancel,initial_guess):
        """Bounded request-local history; every accepted output is a fresh Picard image."""
        policy=self.anderson_policy
        images=[];errors=[];history=[];accepted=rejected=0
        for index in range(self.policy.max_picard_iterations):
            _cancel(cancel);self._coefficients(ec,ev)
            image,it=self._linear(rhs,vector,cancel)
            if self._adaptive_request is not None and self._adaptive_request.rows[-1]['history_reset']:
                images.clear();errors.clear()
            nc,nv,_,_=self._law(image,F,eta,profile,law)
            change=max(float(np.max(np.abs(np.log(nc)-np.log(ec)))),
                       float(np.max(np.abs(np.log(nv)-np.log(ev)))))
            self._coefficients(nc,nv)
            d,_=_diagnostics(self._op,image,rhs,self.policy,enforce=False)
            row=dict(action='not_proposed',picard_merit=_aa._merit(d,self.policy),trial_merit=None,depth_used=0)
            history.append(dict(momentum_linf=d['momentum_linf'],viscosity_log_change=change,
                                linear_iterations=it,anderson=row))
            if d['momentum_linf']<=self.policy.momentum_tolerance and change<=self.policy.viscosity_rtol:
                if self._adaptive_request is not None and not self._adaptive_request.rows[-1]['strict_certified']:
                    # Do not publish a provisional image or carry its differences
                    # into the fresh strict-certification phase.
                    self._adaptive_request.strict_phase=True
                    images.clear();errors.clear()
                    vector,ec,ev=image,nc,nv
                    continue
                _check_diagnostics(d,self.policy)
                acceleration=_aa.summary(policy,len(history),accepted,rejected)
                return self._publish(image,rhs,fx,fz,F,eta,profile,T,None,history,epoch,time,source,cancel,
                                     initial_guess=initial_guess,acceleration=acceleration)
            images.append(image.copy());errors.append(image-vector)
            del images[:-policy.depth-1];del errors[:-policy.depth-1]
            if len(images)>=policy.warmup_maps:
                _cancel(cancel)
                proposal,details=_aa._propose(images,errors,self._op.nv,policy)
                row['depth_used']=details.get('depth_used',0)
                row['action']='rejected_history'
                if proposal is not None:
                    _cancel(cancel)
                    try:
                        ac,av,_,_=self._law(proposal,F,eta,profile,law)
                        self._coefficients(ac,av)
                        ad,_=_diagnostics(self._op,proposal,rhs,self.policy,enforce=False)
                        row['trial_merit']=_aa._merit(ad,self.policy)
                        if row['trial_merit']<=row['picard_merit']:
                            vector,ec,ev=proposal,ac,av
                            accepted+=1;row['action']='accepted'
                            continue
                        row['action']='rejected_true_residual'
                    except (TectonicsError,FloatingPointError,OverflowError):
                        # Numerical invalidity of a proposal is rejectable. Cancellation,
                        # memory refusal and native/linear failures MUST propagate.
                        row['action']='rejected_invalid_trial'
                rejected+=1;images.clear();errors.clear()
            vector,ec,ev=image,nc,nv
            self._coefficients(ec,ev)
        raise TectonicsError('Anderson exceeded fixed nonlinear envelope; no endpoint published; residual='+str(history[-1]['momentum_linf']))

    def _law_inputs(self,T,damage):
        b=self.box;s=self.scales
        with np.errstate(over='raise',invalid='raise'):
            try:tc=(T-s.surface_temperature_k)/s.temperature_scale_k
            except FloatingPointError as exc:raise TectonicsError('temperature scaling outside range') from exc
        def corner(a):return .25*a[:-1,:-1]+.25*a[1:,:-1]+.25*a[:-1,1:]+.25*a[1:,1:]
        tv=corner(tc)
        z=(b.height_m-(np.arange(b.nz)+.5)*(b.height_m/b.nz))/s.depth_scale_m
        zv=(b.height_m-np.arange(1,b.nz)*(b.height_m/b.nz))/s.depth_scale_m
        zc=np.broadcast_to(z[:,None],tc.shape);zv=np.broadcast_to(zv[:,None],tv.shape)
        dc=np.zeros_like(tc) if damage is None else damage
        dv=corner(dc)
        return tc,tv,zc,zv,dc,dv

    def _law(self,vector,F,eta,profile,law):
        u,w,_,_=self._op.split(vector)
        ec,ev=self._op.invariant_sites(u,w)
        if F:
            factors=(F,self.scales.length_m,self.scales.time_s)
            ec=_factored_scale(ec,factors,(eta,),'dimensionless centre strain rate')
            ev=_factored_scale(ev,factors,(eta,),'dimensionless vertex strain rate')
        tc,tv,zc,zv,dc,dv=law
        lim=ConstitutiveLimits()
        _check_fields(tc,zc,ec,dc,lim);_check_fields(tv,zv,ev,dv,lim)
        c=_native_law(profile,tc,zc,ec,dc);v=_native_law(profile,tv,zv,ev,dv)
        return c[0],v[0],c[-1],v[-1]

    def _publish(self,vector,rhs,fx,fz,F,eta,profile,T,damage,history,epoch,time,source,cancel,*,initial_guess=None,acceleration=None):
        op=self._op;L=self.scales.length_m
        u,w,p,_=op.split(vector)
        usi=np.zeros((op.nz,op.nx+1));wsi=np.zeros((op.nz+1,op.nx))
        if F:
            usi[:,1:-1]=_factored_scale(u,(F,L,L),(eta,),'published u')
            wsi[1:-1]=_factored_scale(w,(F,L,L),(eta,),'published w')
            psi=_factored_scale(p,(F,L),(),'published pressure')
            u[:]=_factored_scale(usi[:,1:-1],(eta,),(F,L,L),'returned u normalisation')
            w[:]=_factored_scale(wsi[1:-1],(eta,),(F,L,L),'returned w normalisation')
            p[:]=_factored_scale(psi,(),(F,L),'returned p normalisation')
        else:psi=np.zeros((op.nz,op.nx))
        self._certify_adaptive_publication(vector,rhs,cancel)
        if profile is not None:
            ec,ev,clipc,clipv=self._law(vector,F,eta,profile,self._law_inputs(T,damage))
            self._coefficients(ec,ev)
        ecsi=_factored_scale(op.eta_c,(eta,),(),'published centre viscosity')
        evsi=_factored_scale(op.eta_v,(eta,),(),'published vertex viscosity')
        # Actual viscosity as well as u/p must survive publication accurately.
        self._coefficients(_checked_scale(ecsi,eta,'returned centre viscosity',divide=True),
                           _checked_scale(evsi,eta,'returned vertex viscosity',divide=True))
        if self._adaptive_request is not None:
            # Re-evaluate the nonlinear change on the actual returned viscosity,
            # not just the pre-publication iterate. All original limits apply.
            change=max(float(np.max(np.abs(np.log(op.eta_c)-np.log(self._adaptive_request.cert_c)))),
                       float(np.max(np.abs(np.log(op.eta_v)-np.log(self._adaptive_request.cert_v)))))
            if not math.isfinite(change) or change>self.policy.viscosity_rtol:
                raise TectonicsError('returned viscosity fails strict nonlinear certification')
            history[-1]['viscosity_log_change']=change
        diagnostics,div=_diagnostics(op,vector,rhs,self.policy)
        ic,iv=op.invariant_sites(u,w)
        if F:
            div=_factored_scale(div,(F,L),(eta,),'returned divergence')
            ic=_factored_scale(ic,(F,L),(eta,),'returned centre invariant')
            iv=_factored_scale(iv,(F,L),(eta,),'returned vertex invariant')
        history[-1]['momentum_linf']=diagnostics['momentum_linf']
        arrays=dict(force_x_n_m3=fx,force_z_n_m3=fz,u_m_s=usi,w_m_s=wsi,pressure_pa=psi,divergence_s_1=div,
                    viscosity_cell_pa_s=ecsi,viscosity_vertex_pa_s=evsi,strain_rate_cell_s_1=ic,strain_rate_vertex_s_1=iv)
        if profile is not None:
            arrays.update(temperature_k=T,clipped_cell=clipc,clipped_vertex=clipv)
            if damage is not None:arrays['frozen_damage']=damage
        metadata=dict(schema='atlas.variable-stokes-result.v1',method=_METHOD,box=asdict(self.box),scales=asdict(self.scales),
            rheology=None if profile is None else profile.descriptor(),policy=asdict(self.policy),
            mode='prescribed-viscosity' if profile is None else 'rheology',boundary=_BOUNDARY,gauge=_GAUGE,
            context_id=self._context_id,plan_id=self.identity,source=source,epoch_id=epoch,time_s=time,
            units='SI: m, s, Pa, Pa s, N/m^3; x-right z-up',force_amplitude_n_m3=F,viscosity_reference_pa_s=eta,
            nonlinear_history=history,diagnostics=diagnostics,publication_contract='true-rheology-returned-si-v1',
            strain_collocation='normal centre and shear vertex; symmetric arithmetic reconstruction of missing tensor components',
            R4_status='IN_PROGRESS',physical_validation=False)
        if self.adaptive_inner_policy is not None:
            metadata['adaptive_inner']=_ai.summary(self.adaptive_inner_policy,
                self._adaptive_request,len(history),self.policy)
            metadata['adaptive_inner_history']=[] if self._adaptive_request is None else self._adaptive_request.rows
        if self.preconditioner_reuse_policy is not None:
            rows=[] if self._reuse_request is None else self._reuse_request.rows
            metadata['preconditioner_reuse']=_pr.summary(self.preconditioner_reuse_policy,
                profile.family=='tosi-plastic',len(history),rows)
            metadata['preconditioner_history']=rows
        if acceleration is not None:metadata['nonlinear_acceleration']=acceleration
        if initial_guess is not None:
            metadata['initial_guess']=dict(guess_id=initial_guess.guess_id,descriptor=initial_guess.descriptor())
            arrays.update({'initial_guess_'+k:initial_guess.array(k) for k in ('u_m_s','w_m_s','pressure_pa')})
        _cancel(cancel)
        return VariableStokesSolution(metadata,arrays)


def save_variable_stokes_solution(result,store,*,budget=None,cancel=None):
    from .storage import ArrayStore
    if type(result) is not VariableStokesSolution or not isinstance(store,ArrayStore):raise TectonicsError('typed result/store required')
    policy=store._budget if budget is None else budget
    _cancel(cancel)
    with select_budget(policy).reserve(3*result.nbytes+65536,category='variable-stokes-save'):
        return store.put(result.result_id,{k:result.array(k) for k in result.array_names},result.descriptor(),budget=policy,cancel=cancel)


def load_variable_stokes_solution(store,result_id,*,budget=None,cancel=None):
    from .storage import ArrayStore
    if not isinstance(store,ArrayStore):raise TectonicsError('ArrayStore required')
    _hex(result_id,'variable result');_cancel(cancel);policy=store._budget if budget is None else budget
    meta=store.metadata(result_id)
    if meta is None:raise TectonicsError('variable mechanical snapshot absent')
    a=store.get(result_id,budget=policy)
    if a is None:raise TectonicsError('variable mechanical arrays absent')
    with select_budget(policy).reserve(3*sum(v.nbytes for v in a.values())+131072,category='variable-stokes-restore'):
        out=VariableStokesSolution(meta,a)
        if out.result_id!=result_id:raise TectonicsError('variable mechanical identity differs')
        _cancel(cancel)
        return out
