"""Prepared R3 laws with the existing source context, scheduler and ArrayStore.

SPDX-License-Identifier: AGPL-3.0-only
Only independent local evaluations are batched; this is not a parallel time
integrator. Scientific identity excludes worker count/order. Runtime/source
changes still invalidate it. Immutable inputs and all retained batch/merge
outputs are admitted before work, with native-job draining on cancellation.
"""
from __future__ import annotations
from dataclasses import asdict, replace
from contextlib import contextmanager
import hashlib
import json
import threading

import numpy as np

from ._validation import TectonicsError, input_shape, read_array, snapshot, scalar
from .resources import elements, select_budget
from .reuse import ExecutionContext
from .execution import KernelExecutor, ExecutionPolicy, _AdmittedCall
from .constitutive import (RheologyProfile, ConstitutiveLimits, DiffusiveScales,
                           evaluate_rheology, advance_memory, _inputs, _json, _cancel, _METHOD)


class LawResult:
    """Self-contained immutable response and inputs; no lost profile or units.

    Old results can be restored without claiming their source is current. This
    object is a record, not a permission to reuse a stale live evaluator.
    """
    __slots__=('_metadata','_data','result_id')

    def __init__(self, metadata, arrays):
        if type(metadata) is not dict or metadata.get('schema')!='atlas.constitutive-result.v1':
            raise TectonicsError('unknown constitutive result schema')
        # Restore the recorded profile/units, not current defaults. Hashes bind
        # the record; they do not authenticate an outside producer's claims.
        required_metadata = {'schema','method','plan_id','profile','context_id',
                             'scales','array_units','physics'}
        if not required_metadata.issubset(metadata) or metadata['method'] != _METHOD:
            raise TectonicsError('incomplete or unsupported law metadata')
        for key in ('plan_id','context_id'):
            value=metadata[key]
            if not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):
                raise TectonicsError('invalid recorded '+key)
        profile_record=metadata['profile']
        try:
            profile=RheologyProfile(profile_record['name'],profile_record['family'],
                profile_record['source'],tuple(tuple(x) for x in profile_record['parameters']),
                None if profile_record['viscosity_bounds'] is None else tuple(profile_record['viscosity_bounds']))
            if _json(profile.descriptor()) != _json(profile_record):
                raise TectonicsError('recorded profile identity differs')
            if metadata['scales'] is not None:
                scales=DiffusiveScales(**metadata['scales'])
                if _json(asdict(scales)) != _json(metadata['scales']):
                    raise TectonicsError('invalid recorded scale set')
        except (KeyError,TypeError,ValueError) as exc:
            raise TectonicsError('invalid recorded profile or scales') from exc
        if metadata['array_units'] != 'dimensionless reference units; strain-rate invariant sqrt(e:e/2)':
            raise TectonicsError('unsupported result array units')
        if not isinstance(arrays,dict) or not arrays or len(arrays)>16:
            raise TectonicsError('bounded constitutive arrays required')
        operation=metadata.get('operation','rheology')
        if operation not in ('rheology','memory-step'): raise TectonicsError('unknown local operation')
        if operation=='memory-step':
            if profile.family!='bf23-memory' or 'elapsed_dimensionless' not in metadata:
                raise TectonicsError('memory record needs the selected law and elapsed interval')
            scalar(metadata['elapsed_dimensionless'],'recorded interval',nonnegative=True)
        required=({'temperature','depth','strain_rate_ii','damage','viscosity','stress_ii',
                  'weakening_factor','healing_rate','viscosity_bound_code'} if operation=='rheology'
                  else {'temperature','strain_rate_ii','damage_before','damage_after'})
        optional=set()
        if operation=='rheology' and profile.family in ('tosi-plastic','bf23-memory'):
            required.add('yield_parameter')
        if not required.issubset(arrays) or set(arrays)-required-optional:
            raise TectonicsError('incomplete or unexpected constitutive arrays')
        data=[]; shape=None
        for name,value in sorted(arrays.items()):
            view=snapshot(value,name)
            if shape is None: shape=view.shape
            if view.shape!=shape: raise TectonicsError('constitutive result shapes differ')
            # Store bytes, not shared mutable shape descriptors. No object can
            # re-enable writes or mutate the descriptor seen by another caller.
            owner=view
            while type(owner) is np.ndarray: owner=owner.base
            if type(owner) is not bytes or len(owner)!=view.nbytes:
                raise TectonicsError('result ownership contract failed')
            data.append((name,view.shape,owner))
        md=_json(metadata)
        if len(md)>65536: raise TectonicsError('constitutive metadata too large')
        h=hashlib.sha256(md)
        for name,shape,raw in data:
            h.update(_json([name,list(shape),'float64'])); h.update(raw)
        object.__setattr__(self,'_metadata',md); object.__setattr__(self,'_data',tuple(data))
        object.__setattr__(self,'result_id',h.hexdigest())

    def __setattr__(self,*_):
        raise TectonicsError('constitutive results are immutable')

    def descriptor(self):
        return json.loads(self._metadata)

    @property
    def array_names(self):
        return tuple(k for k,_,_ in self._data)

    @property
    def nbytes(self):
        return len(self._metadata)+sum(len(b) for _,_,b in self._data)

    def array(self,name):
        for k,shape,b in self._data:
            if k==name: return np.frombuffer(b,dtype=np.float64).reshape(shape)
        raise TectonicsError('unknown constitutive array '+str(name))


class _Cancellation:
    def __init__(self,external,aborted): self.external=external; self.aborted=aborted
    def is_set(self): return self.aborted.is_set() or (self.external is not None and self.external.is_set())


class PreparedRheology:
    """Source-verified prepared evaluator; caller-owned, explicit close.

    Uses the existing executor lazily. Processes cannot share this source-bound
    plan and are refused. The normal route is native bulk serial: the registered local-law workloads
    were not faster with threads. An explicit auto/threads policy reuses bounded
    scheduling for verified workload-specific choices, never different physics.
    """
    def __init__(self,profile,*,scales=None,limits=None,execution=None,budget=None):
        if type(profile) is not RheologyProfile: raise TectonicsError('typed profile required')
        if scales is not None and type(scales) is not DiffusiveScales: raise TectonicsError('typed scales required')
        limits=ConstitutiveLimits() if limits is None else limits
        execution=ExecutionPolicy(mode='serial') if execution is None else execution
        if type(limits) is not ConstitutiveLimits or type(execution) is not ExecutionPolicy or execution.mode=='processes':
            raise TectonicsError('typed limits and thread/serial execution policy required')
        self.profile=profile; self.scales=scales; self.limits=limits; self.execution=execution
        self.budget=select_budget(budget); self._closed=False; self._active=False
        self._lock=threading.Lock(); self._executor=None; self._context=None
        self._guard=self.budget.reserve(5*1024**2,category='constitutive-plan')
        self._guard.__enter__()
        try:
            self._context=ExecutionContext('scipy')
            self.identity=hashlib.sha256(_json({'method':_METHOD,'profile':profile.descriptor(),
                'scales':None if scales is None else asdict(scales),'context':self._context.identity})).hexdigest()
        except BaseException:
            self._guard.__exit__(None,None,None)
            raise

    def __setattr__(self,name,value):
        if name in ('profile','scales','limits','execution','budget','identity') and hasattr(self,name):
            raise TectonicsError('prepared law binding is immutable')
        object.__setattr__(self,name,value)

    def __enter__(self):
        if self._closed: raise TectonicsError('prepared law is closed')
        return self

    def __exit__(self,*_): self.close()

    def close(self):
        with self._lock:
            if self._active: raise TectonicsError('join active law evaluation before closing')
            if self._closed: return
            if (self._executor is not None and self._executor._entered and
                threading.get_ident()!=self._executor._owner_thread):
                raise TectonicsError('close the law executor on its driving thread')
            self._closed=True
        try:
            if self._executor is not None: self._executor.close()
        finally:
            try:
                if self._context is not None: self._context.close()
            finally:
                self._guard.__exit__(None,None,None)

    @contextmanager
    def _operation(self,cancel):
        with self._lock:
            if self._closed or self._active: raise TectonicsError('closed or already-driven constitutive plan')
            self._active=True
        try:
            _cancel(cancel); self._context.verify()
            yield
            _cancel(cancel); self._context.verify()
        finally:
            with self._lock: self._active=False

    def evaluate(self,temperature,depth,strain_rate_ii,damage=None,*,units='dimensionless',cancel=None):
        """SI inputs: kelvin, metres, s^-1; damage remains dimensionless.

        Returned input/output arrays are in explicit *dimensionless* reference
        units. Use result.scales in the descriptor for conversions. This avoids
        two different units hiding behind one array name or sample identity.
        """
        if units not in ('dimensionless','SI'): raise TectonicsError('explicit SI or dimensionless units required')
        if units=='SI' and self.scales is None: raise TectonicsError('SI evaluation needs a named scale set')
        if damage is None:
            if self.profile.family=='bf23-memory': raise TectonicsError('explicit initial damage required')
            damage=0.
        args=(temperature,depth,strain_rate_ii,damage)
        shape,n,inputs=_inputs(args,('temperature','depth','rate','damage'),self.limits)
        # Full immutable capture, batch outputs, merge arrays and result bytes.
        # Per-job scratch is separately admitted by the established executor.
        with self._operation(cancel),self.budget.reserve(288*n+32*inputs+65536,category='constitutive-request'):
            captured=[snapshot(v,k) for v,k in zip(args,('temperature','depth','rate','damage'))]
            if units=='SI':
                s=self.scales
                captured[:3]=[(captured[0]-s.surface_temperature_k)/s.temperature_scale_k,
                              captured[1]/s.depth_scale_m,captured[2]*s.time_s]
            views=[snapshot(a,'captured law input') for a in np.broadcast_arrays(*captured)]
            if views[0].shape!=shape: raise TectonicsError('input shapes changed during capture')
            parallel=self.execution.max_workers>1 and (self.execution.mode=='threads' or
                (self.execution.mode=='auto' and n>=self.execution.min_parallel_elements))
            if parallel:
                if self._executor is None:
                    self._executor=KernelExecutor(replace(self.execution,mode='threads'),budget=self.budget)
                    self._executor.__enter__()
                aborted=threading.Event(); token=_Cancellation(cancel,aborted)
                batch=self.limits.batch_points
                def calls():
                    for start in range(0,n,batch):
                        stop=min(start+batch,n); size=stop-start
                        part=tuple(a.reshape(-1)[start:stop] for a in views)
                        def run(job_budget,part=part):
                            return evaluate_rheology(self.profile,*part,limits=self.limits,budget=job_budget,cancel=token)
                        def accept(result,size=size):
                            if not isinstance(result,dict) or any(v.shape!=(size,) for v in result.values()):
                                raise TectonicsError('law worker returned invalid arrays')
                            return result
                        yield _AdmittedCall(run,accept,aborted.set,size,512*size+131072)
                stream=self._executor._admitted_calls(calls(),cancel=token)
                pieces=[]
                try:
                    pieces.extend(stream)
                finally: stream.close()
                response={k:np.concatenate([r[k] for r in pieces]).reshape(shape) for k in pieces[0]}
            else:
                response=evaluate_rheology(self.profile,*views,limits=self.limits,budget=self.budget,cancel=cancel)
            arrays=dict(zip(('temperature','depth','strain_rate_ii','damage'),views)); arrays.update(response)
            md={'schema':'atlas.constitutive-result.v1','method':_METHOD,'plan_id':self.identity,
                'profile':self.profile.descriptor(),'context_id':self._context.identity,
                'scales':None if self.scales is None else asdict(self.scales),
                'array_units':'dimensionless reference units; strain-rate invariant sqrt(e:e/2)',
                'physics':'local response only; not a PDE solution or physically accepted plate generation'}
            _cancel(cancel)
            return LawResult(md,arrays)

    def advance(self,damage,strain_rate_ii,temperature,elapsed,*,units='dimensionless',cancel=None):
        """Source-bound material-point memory interval, with all continuation data.

        Coefficients are held constant over this explicit interval. No advection,
        spatial filtering or operator splitting is hidden here. Native buffered
        evaluation is serial; the execution policy controls evaluate(), not a
        sequence of time steps. The result retains the old and new memory.
        """
        from ._validation import scalar
        if self.profile.family!='bf23-memory': raise TectonicsError('selected law has no memory')
        if units not in ('dimensionless','SI'): raise TectonicsError('known units required')
        if units=='SI' and self.scales is None: raise TectonicsError('SI advance requires scales')
        elapsed=scalar(elapsed,'elapsed time',nonnegative=True)
        args=(damage,strain_rate_ii,temperature)
        shape,n,inputs=_inputs(args,('damage','rate','temperature'),self.limits)
        with self._operation(cancel),self.budget.reserve(160*n+32*inputs+65536,category='constitutive-memory-record'):
            d,e,T=(snapshot(v,k) for v,k in zip(args,('damage','rate','temperature')))
            if units=='SI':
                e=e*self.scales.time_s
                T=(T-self.scales.surface_temperature_k)/self.scales.temperature_scale_k
                elapsed/=self.scales.time_s
            d,e,T=(snapshot(v,'memory input') for v in np.broadcast_arrays(d,e,T))
            next_d=advance_memory(self.profile,d,e,T,elapsed,limits=self.limits,budget=self.budget,cancel=cancel)
            md={'schema':'atlas.constitutive-result.v1','operation':'memory-step',
                'method':_METHOD,'plan_id':self.identity,'profile':self.profile.descriptor(),
                'context_id':self._context.identity,'elapsed_dimensionless':elapsed,
                'scales':None if self.scales is None else asdict(self.scales),
                'array_units':'dimensionless reference units; strain-rate invariant sqrt(e:e/2)',
                'physics':'constant-coefficient material-point interval, not an advective or coupled thermal evolution'}
            return LawResult(md,dict(temperature=T,strain_rate_ii=e,damage_before=d,damage_after=next_d))

    @property
    def execution_statistics(self):
        return None if self._executor is None else self._executor.statistics()


def save_law_result(result,store,*,budget=None,cancel=None):
    """Reuse the existing verified, lossless, deduplicated store."""
    from .storage import ArrayStore
    if type(result) is not LawResult or not isinstance(store,ArrayStore):
        raise TectonicsError('typed law result and ArrayStore required')
    _cancel(cancel); policy=store._budget if budget is None else budget
    with select_budget(policy).reserve(3*result.nbytes+65536,category='constitutive-save'):
        return store.put(result.result_id,{k:result.array(k) for k in result.array_names},
                         result.descriptor(),budget=policy,cancel=cancel)


def load_law_result(store,result_id,*,budget=None,cancel=None):
    """Restore original recorded source identity; never rebind it to current code."""
    from .storage import ArrayStore
    if not isinstance(store,ArrayStore) or not isinstance(result_id,str) or len(result_id)!=64:
        raise TectonicsError('ArrayStore and result digest required')
    _cancel(cancel); policy=store._budget if budget is None else budget
    metadata=store.metadata(result_id)
    arrays=store.get(result_id,budget=policy)
    if arrays is None or metadata is None: raise TectonicsError('stored law result not found')
    with select_budget(policy).reserve(3*sum(v.nbytes for v in arrays.values())+131072,category='constitutive-restore'):
        result=LawResult(metadata,arrays)
        if result.result_id!=result_id: raise TectonicsError('stored law result identity mismatch')
        _cancel(cancel)
        return result
