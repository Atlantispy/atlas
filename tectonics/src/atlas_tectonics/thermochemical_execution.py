"""Source-bound R4.2 thermal/composition steps and explicit R4.3 nonlinear feedback.

SPDX-License-Identifier: AGPL-3.0-only
R4 remains IN_PROGRESS. The two accepted fields are evolved, not decorative input
textures. Strang intermediates and RK-stage velocities are NOT labelled as the
accepted final state's simultaneous mechanical solution. R4.3 explicitly enables
Tosi variable-viscosity/yielding feedback; full convection benchmark acceptance
and multidimensional damage remain future work. Legacy R4.2 is not relabelled.
"""
from __future__ import annotations
from . import preconditioner_reuse as _pr
from . import adaptive_inner as _ai
from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json
import math
import threading
import numpy as np
from ._validation import TectonicsError, scalar, text, input_shape, read_array, frozen
from .resources import select_budget, MemoryLimitError
from .constitutive import _cancel, _json
from .reuse import ExecutionContext
from .stokes import face_force_from_density, StokesSolvePolicy
from .stokes_execution import PreparedStokes2D, _native_lease, _factored_scale, _hex
from .thermochemical import (ThermochemicalProblem, ThermochemicalPolicy, _Diffusion2D,
                            _METHOD, _BOUND_TOL, _TIME_RTOL, _PUBLICATION_CONTRACT,
                            _check_fields, _reference_transfers, _digest)


def _endpoint_time(start,dt,policy):
    """Require the published clock interval to describe the integrated duration.

    A merely increasing time can round 3 seconds to 4 at a large named epoch.
    We neither silently integrate 4 nor relabel 3 as 4. Reject intervals whose
    represented duration fails this relative precision guard. Ordinary geological
    timesteps are unaffected; an unrepresentable fine timestep needs an explicitly
    rebased epoch or a different interval chosen by the caller.
    """
    end=start+dt
    if dt*.5==0 or not math.isfinite(end) or end<=start:
        raise TectonicsError('time interval cannot advance the named epoch in binary64')
    represented=end-start
    precision=min(policy.inventory_rtol,_TIME_RTOL)
    if abs(2*(.5*dt)-dt)/dt>precision:
        raise TectonicsError('represented diffusion half intervals differ from integrated dt')
    if (not math.isfinite(represented) or
            abs(represented-dt)/dt>precision):
        raise TectonicsError('represented clock interval differs from integrated dt; use an explicit suitable epoch/interval')
    return end


def _check_step_record(record, time_s, source):
    """Validate decoded records; hashes are integrity, not scientific signatures."""
    keys={'method','dt_s','input_time_s','source','policy','velocity_mode','velocity_source',
          'stage_flow_ids','heating_sha256','balances'}
    if (type(record) is not dict or set(record) not in (keys,keys|{'publication_contract'},keys|{'publication_contract','nonlinear_mechanics'})
            or record['method']!=_METHOD):
        raise TectonicsError('complete canonical evolution record required')
    dt=scalar(record['dt_s'],'stored step interval',positive=True)
    start=scalar(record['input_time_s'],'stored initial time')
    if start+dt!=time_s or not time_s>start or record['source']!=source:
        raise TectonicsError('stored time/source does not describe this endpoint')
    try: policy=ThermochemicalPolicy(**record['policy'])
    except (TypeError,KeyError) as exc: raise TectonicsError('invalid stored step policy') from exc
    if _json(asdict(policy))!=_json(record['policy']): raise TectonicsError('noncanonical stored policy')
    # Old snapshots remain exactly decodable, but never acquire new guarantees.
    # Their execution ID still prevents silent continuation with changed source.
    if 'publication_contract' in record:
        if record['publication_contract']!=_PUBLICATION_CONTRACT:
            raise TectonicsError('unknown thermochemical publication contract')
        if _endpoint_time(start,dt,policy)!=time_s:
            raise TectonicsError('stored endpoint fails its clock precision contract')
    if record['velocity_mode'] not in ('buoyancy-coupled-constant-viscosity','buoyancy-coupled-variable-viscosity','prescribed-frozen-MAC'):
        raise TectonicsError('unknown stored velocity mode')
    if record['velocity_mode']=='prescribed-frozen-MAC': text(record['velocity_source'],'velocity provenance')
    elif record['velocity_source'] is not None: raise TectonicsError('coupled velocity has no prescribed source')
    if type(record['stage_flow_ids']) is not list or len(record['stage_flow_ids'])!=2:
        raise TectonicsError('two RK stage identities required')
    for v in record['stage_flow_ids']: _hex(v,'stage flow')
    if record['velocity_mode']=='buoyancy-coupled-variable-viscosity':
        from .variable_stokes import NonlinearStokesPolicy
        from .variable_stokes_execution import _check_diagnostics
        try:
            nm=record['nonlinear_mechanics'];np_=NonlinearStokesPolicy(**nm['policy'])
            _hex(nm['profile_id'],'coupled rheology')
            warm='nonlinear_start' in nm
            cross=warm and nm['nonlinear_start']=='previous-stage1'
            if warm and nm['nonlinear_start'] not in ('rk-stage0','previous-stage1'):
                raise TectonicsError('unsupported stored nonlinear starting policy')
            adapted='adaptive_inner_policy' in nm
            ip=None
            if adapted:
                ip=_ai.AdaptiveInnerPolicy(**nm['adaptive_inner_policy']);_ai.check_policy(ip,np_)
                if _json(asdict(ip))!=_json(nm['adaptive_inner_policy']):raise TectonicsError('noncanonical adaptive policy')
            reused='preconditioner_reuse_policy' in nm
            pp=None
            if reused:
                pp=_pr.PreconditionerReusePolicy(**nm['preconditioner_reuse_policy']);_pr.check_policy(pp,np_)
                if _json(asdict(pp))!=_json(nm['preconditioner_reuse_policy']):raise TectonicsError('noncanonical reuse policy')
            accelerated='anderson_policy' in nm
            ap=None
            if accelerated:
                from .anderson import AndersonPolicy, check_policy, check_summary
                ap=AndersonPolicy(**nm['anderson_policy']);check_policy(ap,np_)
                if _json(asdict(ap))!=_json(nm['anderson_policy']):raise TectonicsError('noncanonical acceleration policy')
            if set(nm)!={'profile_id','policy','stages'}|({'nonlinear_start'} if warm else set())|({'anderson_policy'} if accelerated else set())|({'cross_step_start'} if cross else set())|({'preconditioner_reuse_policy'} if reused else set())|({'adaptive_inner_policy'} if adapted else set()):
                raise TectonicsError('noncanonical stored nonlinear starting record')
            if len(nm['stages'])!=2 or _json(asdict(np_))!=_json(nm['policy']):
                raise TectonicsError('invalid nonlinear stages/policy')
            if cross:
                cs=nm['cross_step_start']
                if type(cs) is not dict or set(cs)!={'input_state_id','input_guess_id',
                        'input_stage1_result_id','mechanical_plan_id','output_guess_id'}:
                    raise TectonicsError('incomplete cross-step starting record')
                for key in ('input_state_id','mechanical_plan_id','output_guess_id'):
                    _hex(cs[key],key)
                if cs['input_guess_id'] is None:
                    if cs['input_stage1_result_id'] is not None:
                        raise TectonicsError('cold first stage cannot claim a previous result')
                else:
                    _hex(cs['input_guess_id'],'previous starting guess')
                    _hex(cs['input_stage1_result_id'],'previous second-stage result')
            for i,s in enumerate(nm['stages']):
                if s['result_id']!=record['stage_flow_ids'][i]:raise TectonicsError('nonlinear stage identity differs')
                if warm:
                    if i==0:
                        expected=(cs['input_guess_id'],cs['input_stage1_result_id']) if cross else (None,None)
                        if (s['initial_guess_id'],s['initial_guess_result_id'])!=expected:
                            raise TectonicsError('first RK stage starting data differs from declared policy')
                    else:
                        _hex(s['initial_guess_id'],'stage starting guess')
                        if s['initial_guess_result_id']!=record['stage_flow_ids'][0]:
                            raise TectonicsError('second RK stage guess must come from the first stage')
                elif 'initial_guess_id' in s or 'initial_guess_result_id' in s:
                    raise TectonicsError('unrecorded nonlinear starting policy')
                if adapted:
                    _ai.check_stage(s['adaptive_inner'],s['adaptive_inner_history'],
                        s['nonlinear_iterations'],s['linear_iterations'],np_,ip)
                elif 'adaptive_inner' in s or 'adaptive_inner_history' in s:
                    raise TectonicsError('undeclared adaptive stage')
                if reused:_pr.check_summary(s['preconditioner_reuse'],s['nonlinear_iterations'],pp)
                elif 'preconditioner_reuse' in s:raise TectonicsError('undeclared stage preconditioner reuse')
                if accelerated:check_summary(s['nonlinear_acceleration'],s['nonlinear_iterations'],ap)
                elif 'nonlinear_acceleration' in s:raise TectonicsError('undeclared stage acceleration')
                _check_diagnostics(s['diagnostics'],np_)
                if type(s['nonlinear_iterations']) is not int or not 1<=s['nonlinear_iterations']<=np_.max_picard_iterations:
                    raise TectonicsError('invalid coupled nonlinear iteration count')
                if type(s['linear_iterations']) is not int or not 0<=s['linear_iterations']<=np_.max_picard_iterations*np_.restart*np_.max_cycles:
                    raise TectonicsError('invalid coupled linear iteration count')
        except (TypeError,KeyError,ValueError) as exc:raise TectonicsError('invalid nonlinear mechanics record') from exc
    elif 'nonlinear_mechanics' in record:
        raise TectonicsError('unexpected nonlinear mechanics record')
    _hex(record['heating_sha256'],'total heating')
    names={'heat_before_j','heat_after_j','heat_change_j','source_heat_j','bottom_outward_heat_j',
           'top_outward_heat_j','heat_residual_j','heat_relative_residual','composition_before_m3',
           'composition_after_m3','composition_change_m3','complement_before_m3','complement_after_m3',
           'composition_relative_residual','advective_local_residual','composition_bound_excursion',
           'courant_stage0','courant_stage1','dt_divergence_stage0','dt_divergence_stage1'}
    b=record['balances']
    if type(b) is not dict or set(b)!=names: raise TectonicsError('incomplete evolution balances')
    for name,v in b.items(): scalar(v,'stored '+name)
    for name in ('heat_relative_residual','composition_relative_residual','advective_local_residual'):
        if not 0<=b[name]<=policy.inventory_rtol: raise TectonicsError('stored balance fails its unchanged gate')
    if not 0<=b['composition_bound_excursion']<=_BOUND_TOL: raise TectonicsError('stored composition bound fails')
    for name in ('courant_stage0','courant_stage1'):
        if not 0<=b[name]<=policy.outgoing_courant: raise TectonicsError('stored Courant limit fails')
    return policy


class ThermochemicalState:
    """Self-contained immutable cell-average state; parent IDs are provenance only.

    A saved state includes its complete problem definition and current arrays;
    cross-step mode also owns its explicit previous stage-1 starting data.
    it does not need a chain of earlier deltas to decode. Continued calculation
    requires the recorded source/execution identity, rather than silently rebasing.
    No full material-cohort/history migration is claimed for one binary fraction.
    """
    __slots__=('problem','_metadata','_temperature','_composition','_next_initial_guess','state_id')
    def __init__(self,problem,temperature_k,composition,*,time_s,source,parent_id=None,
                 step_index=0,execution_id=None,step_record=None,next_initial_guess=None,budget=None):
        if type(problem) is not ThermochemicalProblem: raise TectonicsError('typed thermochemical problem required')
        n=problem.box.nx*problem.box.nz
        if n>ThermochemicalPolicy().max_cells:
            raise TectonicsError('state exceeds current finite cell envelope')
        shape=(problem.box.nz,problem.box.nx)
        if input_shape(temperature_k)!=shape or input_shape(composition)!=shape:
            raise TectonicsError('initial cell-average shapes differ from the problem')
        text(source,'state provenance')
        if len(source)>4096: raise TectonicsError('state source too long')
        time_s=scalar(time_s,'state time')
        if type(step_index) is not int or not 0<=step_index<=2**53:
            raise TectonicsError('invalid time-step index')
        if step_index==0:
            if parent_id is not None or execution_id is not None or step_record is not None:
                raise TectonicsError('initial state may not forge a completed evolution step')
        else:
            _hex(parent_id,'parent state');_hex(execution_id,'evolution execution')
            stored_policy=_check_step_record(step_record,time_s,source)
            mode=step_record['velocity_mode']
            if mode=='buoyancy-coupled-variable-viscosity':
                if problem.mechanical_mode!='variable-r4.3' or step_record['nonlinear_mechanics']['profile_id']!=problem.rheology.profile_id:
                    raise TectonicsError('stored nonlinear rheology differs from problem')
                nm=step_record['nonlinear_mechanics']
                if 'adaptive_inner_policy' in nm:
                    if problem.rheology.family not in ('constant','tosi-linear','tosi-plastic'):
                        raise TectonicsError('stored adaptive policy uses unsupported rheology')
                    active=problem.rheology.family=='tosi-plastic'
                    if any(stage['adaptive_inner']['active']!=active for stage in nm['stages']):
                        raise TectonicsError('stored adaptive activation differs from rheology')
            elif mode=='buoyancy-coupled-constant-viscosity' and problem.mechanical_mode!='constant-r4.2':
                raise TectonicsError('constant mechanical record cannot describe a variable-rheology step')
            if step_index>stored_policy.max_steps: raise TectonicsError('stored step index exceeds declared envelope')
        cross=(step_record is not None and
               step_record.get('nonlinear_mechanics',{}).get('nonlinear_start')=='previous-stage1')
        if cross:
            from .variable_stokes_execution import NonlinearStokesGuess
            if type(next_initial_guess) is not NonlinearStokesGuess:
                raise TectonicsError('cross-step endpoint requires complete immutable starting data')
            nm=step_record['nonlinear_mechanics'];cs=nm['cross_step_start']
            gm=next_initial_guess.descriptor()
            if (cs['input_state_id']!=parent_id or
                    (cs['input_guess_id'] is None)!=(step_index==1)):
                raise TectonicsError('previous starting data must belong to the accepted parent step')
            if (gm['time_s']!=time_s or gm['epoch_id']!=problem.epoch_id or
                    _json(gm['box'])!=_json(asdict(problem.box)) or
                    _json(gm['scales'])!=_json(asdict(problem.scales)) or
                    _json(gm['rheology'])!=_json(problem.rheology.descriptor()) or
                    gm['plan_id']!=cs['mechanical_plan_id'] or
                    gm['source_result_id']!=step_record['stage_flow_ids'][1] or
                    next_initial_guess.guess_id!=cs['output_guess_id']):
                raise TectonicsError('saved next guess is not this accepted step second-stage solution')
        elif next_initial_guess is not None:
            raise TectonicsError('starting data supplied without a completed cross-step policy')
        with select_budget(budget).reserve(80*n+131072+(128*n+262144 if cross else 0),category='thermochemical-state'):
            T=read_array(temperature_k,'temperature',ndim=2);C=read_array(composition,'composition',ndim=2)
            _,excursion=_check_fields(problem,T,C)
            meta=dict(schema='atlas.thermochemical-state.v1',problem=problem.descriptor(),
                problem_id=problem.problem_id,time_s=time_s,source=source,parent_id=parent_id,
                step_index=step_index,execution_id=execution_id,step_record=step_record,
                composition_bound_excursion=excursion,units='SI cell averages; x-right z-up; budgets per 1 m thickness',
                R4_complete=False,physical_validation=False)
            if cross:
                meta['schema']='atlas.thermochemical-state.v2'
                meta['next_initial_guess']=dict(guess_id=next_initial_guess.guess_id,
                                                descriptor=next_initial_guess.descriptor())
            raw=_json(meta)
            if len(raw)>131072: raise TectonicsError('state metadata exceeds finite envelope')
            self.problem=problem;self._metadata=raw
            self._temperature=T.tobytes();self._composition=C.tobytes()
            self._next_initial_guess=next_initial_guess
            h=hashlib.sha256(raw+self._temperature+self._composition)
            if cross:
                for key in ('u_m_s','w_m_s','pressure_pa'):
                    h.update(next_initial_guess.array(key).tobytes())
            self.state_id=h.hexdigest()

    def __setattr__(self,k,v):
        if hasattr(self,k): raise TectonicsError('thermochemical state is immutable')
        object.__setattr__(self,k,v)
    def descriptor(self): return json.loads(self._metadata)
    @property
    def time_s(self): return self.descriptor()['time_s']
    @property
    def step_index(self): return self.descriptor()['step_index']
    @property
    def nbytes(self):
        return (len(self._metadata)+len(self._temperature)+len(self._composition)+
                (0 if self._next_initial_guess is None else self._next_initial_guess.nbytes))
    @property
    def next_initial_guess(self):
        """Immutable preceding stage-1 fields for the next stage-0 solve, not endpoint flow."""
        return self._next_initial_guess
    @property
    def array_names(self):
        return ('temperature_k','composition')+(() if self._next_initial_guess is None else
               ('next_guess_u_m_s','next_guess_w_m_s','next_guess_pressure_pa'))
    def array(self,name):
        if self._next_initial_guess is not None and name in self.array_names[2:]:
            return self._next_initial_guess.array(name[len('next_guess_'):])
        if name not in ('temperature_k','composition'): raise TectonicsError('unknown thermochemical field')
        raw=self._temperature if name=='temperature_k' else self._composition
        return np.frombuffer(raw,dtype='f8').reshape(self.problem.box.nz,self.problem.box.nx)

    @classmethod
    def restore(cls,meta,arrays,*,budget=None):
        try:
            cross=meta.get('schema')=='atlas.thermochemical-state.v2'
            names={'temperature_k','composition'}
            guess=None
            if cross:
                names|={'next_guess_u_m_s','next_guess_w_m_s','next_guess_pressure_pa'}
            if (meta.get('schema') not in ('atlas.thermochemical-state.v1','atlas.thermochemical-state.v2')
                    or set(arrays)!=names):
                raise TectonicsError('incomplete thermal/composition/starting snapshot')
            if cross:
                from .variable_stokes_execution import NonlinearStokesGuess
                entry=meta['next_initial_guess']
                if type(entry) is not dict or set(entry)!={'guess_id','descriptor'}:
                    raise TectonicsError('incomplete stored next-guess identity')
                guess=NonlinearStokesGuess.restore(entry['descriptor'],
                    {k:arrays['next_guess_'+k] for k in ('u_m_s','w_m_s','pressure_pa')},
                    entry['guess_id'],budget=budget)
            p=ThermochemicalProblem.from_descriptor(meta['problem'])
            out=cls(p,arrays['temperature_k'],arrays['composition'],time_s=meta['time_s'],source=meta['source'],
                parent_id=meta['parent_id'],step_index=meta['step_index'],execution_id=meta['execution_id'],
                step_record=meta['step_record'],next_initial_guess=guess,budget=budget)
            if _json(out.descriptor())!=_json(meta): raise TectonicsError('state metadata/array mismatch')
            return out
        except MemoryLimitError:
            raise
        except (ValueError,TypeError,KeyError) as exc:
            raise TectonicsError('invalid thermal/composition snapshot') from exc


class PrescribedMACVelocity:
    """Frozen, explicitly authored divergence-free velocity; not a mechanics claim."""
    __slots__=('box','source','_u','_w','velocity_id')
    def __init__(self,box,u_m_s,w_m_s,*,source,budget=None):
        from .stokes import StokesBox2D
        if type(box) is not StokesBox2D: raise TectonicsError('typed MAC box required')
        if input_shape(u_m_s)!=(box.nz,box.nx+1) or input_shape(w_m_s)!=(box.nz+1,box.nx):
            raise TectonicsError('velocity must include all normal wall faces')
        text(source,'velocity source')
        if len(source)>4096: raise TectonicsError('velocity source too long')
        with select_budget(budget).reserve(64*(box.nx+1)*(box.nz+1)+65536,category='thermochemical-velocity'):
            u=read_array(u_m_s,'u');w=read_array(w_m_s,'w')
            if np.any(u[:,[0,-1]]!=0) or np.any(w[[0,-1],:]!=0):
                raise TectonicsError('closed-box normal velocities must be exactly zero')
            self.box=box;self.source=source;self._u=u.tobytes();self._w=w.tobytes()
            self.velocity_id=hashlib.sha256(_json([asdict(box),source])+self._u+self._w).hexdigest()
    def __setattr__(self,k,v):
        if hasattr(self,k): raise TectonicsError('prescribed velocity is immutable')
        object.__setattr__(self,k,v)
    def array(self,name):
        if name=='u_m_s': return np.frombuffer(self._u,dtype='f8').reshape(self.box.nz,self.box.nx+1)
        if name=='w_m_s': return np.frombuffer(self._w,dtype='f8').reshape(self.box.nz+1,self.box.nx)
        raise TectonicsError('unknown velocity array')


class ThermochemicalStep:
    """Accepted endpoint plus auditable interval transfers and stage velocities.

    flux_x/z_increment contain dt*u*q/dx and dt*w*q/dz, averaged over SSP stages;
    multiplying by cell volume yields extensive shared-face transports. Field 0
    is temperature; field 1 composition. Diffusive boundary heat is separate.
    """
    __slots__=('before','state','_metadata','_arrays','result_id')
    def __init__(self,before,state,metadata,arrays):
        if type(before) is not ThermochemicalState or type(state) is not ThermochemicalState:
            raise TectonicsError('typed step endpoints required')
        if before.problem.problem_id!=state.problem.problem_id or state.descriptor()['parent_id']!=before.state_id:
            raise TectonicsError('step endpoints are not parent and successor')
        b=before.problem.box
        shapes={'flux_x_increment':(2,b.nz,b.nx+1),'flux_z_increment':(2,b.nz+1,b.nx),
                'u_stage0_m_s':(b.nz,b.nx+1),'u_stage1_m_s':(b.nz,b.nx+1),
                'w_stage0_m_s':(b.nz+1,b.nx),'w_stage1_m_s':(b.nz+1,b.nx),
                'total_heating_w_m3':(b.nz,b.nx)}
        if set(arrays)!=set(shapes) or metadata.get('schema')!='atlas.thermochemical-step.v1':
            raise TectonicsError('incomplete thermochemical step')
        if metadata.get('before_id')!=before.state_id or metadata.get('after_id')!=state.state_id:
            raise TectonicsError('step identities differ from endpoints')
        if state.step_index!=before.step_index+1 or metadata.get('method')!=_METHOD:
            raise TectonicsError('nonsequential evolution step')
        record=state.descriptor()['step_record']
        if _json(record)!=_json(metadata.get('record')) or record['input_time_s']!=before.time_s:
            raise TectonicsError('step record does not describe both endpoints')
        nm=record.get('nonlinear_mechanics',{})
        if nm.get('nonlinear_start')=='previous-stage1':
            previous=before.next_initial_guess;cs=nm['cross_step_start']
            if (cs['input_guess_id']!=(None if previous is None else previous.guess_id) or
                    cs['input_stage1_result_id']!=(None if previous is None else previous.descriptor()['source_result_id'])):
                raise TectonicsError('step guess provenance differs from its accepted parent')
        owned=[]
        for k,shape in sorted(shapes.items()):
            if input_shape(arrays[k])!=shape: raise TectonicsError('wrong step-array shape')
            a=read_array(arrays[k],k);owned.append((k,shape,a.tobytes()))
        self.before=before;self.state=state;self._metadata=_json(metadata);self._arrays=tuple(owned)
        h=hashlib.sha256(self._metadata+before.state_id.encode()+state.state_id.encode())
        for k,shape,raw in owned: h.update(_json([k,shape]));h.update(raw)
        self.result_id=h.hexdigest()
    def __setattr__(self,k,v):
        if hasattr(self,k): raise TectonicsError('thermochemical step is immutable')
        object.__setattr__(self,k,v)
    def descriptor(self): return json.loads(self._metadata)
    @property
    def array_names(self): return tuple(k for k,_,_ in self._arrays)
    @property
    def nbytes(self): return self.before.nbytes+self.state.nbytes+len(self._metadata)+sum(len(a) for _,_,a in self._arrays)
    def array(self,key):
        for k,shape,raw in self._arrays:
            if k==key: return np.frombuffer(raw,dtype='f8').reshape(shape)
        raise TectonicsError('unknown step array')


class CourantLimitError(TectonicsError):
    """No partial state published. The caller must explicitly reduce its interval."""


def _courant_arrays(box,u,w,dt,policy):
    dx=box.width_m/box.nx;dz=box.height_m/box.nz
    cx=_factored_scale(u,(dt,),(dx,),'horizontal Courant field')
    cz=_factored_scale(w,(dt,),(dz,),'vertical Courant field')
    outgoing=np.maximum(cx[:,1:],0)+np.maximum(-cx[:,:-1],0)+np.maximum(cz[1:],0)+np.maximum(-cz[:-1],0)
    maxout=float(np.max(outgoing))
    if not math.isfinite(maxout):
        raise CourantLimitError('nonfinite outgoing Courant sum; no partial state or automatic retry')
    if maxout>policy.outgoing_courant:
        limit=dt*(policy.outgoing_courant/maxout)
        raise CourantLimitError(
            f'outgoing Courant sum {maxout:.17g} exceeds explicit MC bound '
            f'{policy.outgoing_courant:.17g} at dt_s={dt:.17g}; '
            f'same-velocity timestep ceiling is {limit:.17g} s '
            '(advisory only: changed stages must be checked again); no auto-substepping')
    # Relative divergence is checked on the actual supplied SI velocities.
    div=np.diff(cx,axis=1)+np.diff(cz,axis=0)
    velocity_scale=max(float(np.max(np.abs(cx))),float(np.max(np.abs(cz))))
    maxdiv=float(np.max(np.abs(div)))
    if maxdiv>policy.velocity_divergence_rtol*velocity_scale:
        raise TectonicsError('transport velocity is not discretely incompressible')
    return cx,cz,maxout,maxdiv


class PreparedThermochemical2D:
    """One-driving-thread prepared spectral/transport/constant-Stokes calculation.

    Preparation retains only O(N) transform data and one dt coefficient set.
    Caller-owned accepted states stay immutable. Every advance is atomic: failures
    or cancellation publish no endpoint. Sequential physical steps are NOT jobs
    sent to independent workers. No new scheduler or persistence implementation.
    """
    def __init__(self,problem,*,policy=None,stokes_policy=None,nonlinear_policy=None,nonlinear_start='zero-rate',anderson_policy=None,preconditioner_reuse_policy=None,adaptive_inner_policy=None,backend='numba',budget=None,cancel=None):
        if type(problem) is not ThermochemicalProblem: raise TectonicsError('typed thermochemical problem required')
        policy=ThermochemicalPolicy() if policy is None else policy
        if type(policy) is not ThermochemicalPolicy: raise TectonicsError('typed thermal policy required')
        if problem.box.nx*problem.box.nz>policy.max_cells: raise TectonicsError('thermal cell count exceeds policy')
        if backend not in ('numba','reference'): raise TectonicsError('explicit numba or NumPy verification backend required')
        self.problem=problem;self.policy=policy;self.backend=backend;self.budget=select_budget(budget)
        self.stokes_policy=StokesSolvePolicy() if stokes_policy is None else stokes_policy
        if type(self.stokes_policy) is not StokesSolvePolicy: raise TectonicsError('typed Stokes policy required')
        if problem.mechanical_mode == 'variable-r4.3':
            from .variable_stokes import NonlinearStokesPolicy
            nonlinear_policy=NonlinearStokesPolicy() if nonlinear_policy is None else nonlinear_policy
            if type(nonlinear_policy) is not NonlinearStokesPolicy:
                raise TectonicsError('typed nonlinear mechanical policy required')
            if stokes_policy is not None:
                raise TectonicsError('use nonlinear_policy for variable mechanics; constant stokes_policy would be ignored')
        elif nonlinear_policy is not None:
            raise TectonicsError('constant rheology uses stokes_policy, not an unused nonlinear policy')
        if type(nonlinear_start) is not str or nonlinear_start not in ('zero-rate','rk-stage0','previous-stage1'):
            raise TectonicsError('explicit zero-rate, rk-stage0 or previous-stage1 nonlinear start required')
        if nonlinear_start!='zero-rate' and nonlinear_policy is None:
            raise TectonicsError('nonlinear starting policy requires variable mechanics')
        if nonlinear_start=='previous-stage1' and problem.rheology.family=='bf23-memory':
            raise TectonicsError('cross-step starting policy does not support evolving BF damage')
        if anderson_policy is not None:
            from .anderson import check_policy
            if nonlinear_policy is None:raise TectonicsError('Anderson requires variable mechanics')
            check_policy(anderson_policy,nonlinear_policy)
        if preconditioner_reuse_policy is not None:
            _pr.check_policy(preconditioner_reuse_policy,nonlinear_policy)
            if problem.rheology.family not in ('constant','tosi-linear','tosi-plastic'):
                raise TectonicsError('preconditioner reuse supports constant/Tosi only')
        if adaptive_inner_policy is not None:
            _ai.check_policy(adaptive_inner_policy,nonlinear_policy)
            if problem.rheology.family not in ('constant','tosi-linear','tosi-plastic'):
                raise TectonicsError('adaptive inner supports constant/Tosi only')
        self.adaptive_inner_policy=adaptive_inner_policy
        self.preconditioner_reuse_policy=preconditioner_reuse_policy
        self.anderson_policy=anderson_policy
        self.nonlinear_policy=nonlinear_policy;self.nonlinear_start=nonlinear_start
        self._stage_mechanics=[]
        self._owner=threading.get_ident();self._active=False;self._closed=False
        self._mechanics=None;self._context=None;self._diffusion=None
        self._guard=self.budget.reserve(6*1024**2+128*problem.box.nx*problem.box.nz,category='thermochemical-plan-retained')
        self._guard.__enter__()
        try:
            _cancel(cancel)
            # Imported only by explicit preparation; the old NumPy-only route remains.
            from . import _thermochemical_native as native
            self._native=native
            if backend=='numba':
                a=np.zeros((2,2,2));cx=np.zeros((2,3));cz=np.zeros((3,2));fx=np.empty((2,2,3));fz=np.empty((2,3,2))
                walls=((problem.boundary.bottom_temperature_k,problem.boundary.top_temperature_k)
                       if problem.boundary.kind=='fixed-top-bottom' else None)
                native.face_transfers(a,cx,cz,fx,fz,walls);native.euler_update(a,fx,fz,a.copy());native.sum_compensated(a)
            self._diffusion=_Diffusion2D(problem)
            self._context=ExecutionContext('numba' if backend=='numba' else 'scipy')
            binding=dict(method=_METHOD,problem=problem.descriptor(),policy=asdict(policy),
                stokes_policy=asdict(self.stokes_policy),backend=backend,context=self._context.identity)
            if nonlinear_policy is not None:
                binding['nonlinear_policy']=asdict(nonlinear_policy)
            if nonlinear_start!='zero-rate':binding['nonlinear_start']=nonlinear_start
            if anderson_policy is not None:binding['anderson_policy']=asdict(anderson_policy)
            if preconditioner_reuse_policy is not None:binding['preconditioner_reuse_policy']=asdict(preconditioner_reuse_policy)
            if adaptive_inner_policy is not None:binding['adaptive_inner_policy']=asdict(adaptive_inner_policy)
            self.identity=_digest(binding)
            _cancel(cancel)
        except BaseException:
            self._context=None;self._diffusion=None;self._closed=True
            self._guard.__exit__(None,None,None)
            raise
    def __setattr__(self,k,v):
        if k in ('problem','policy','backend','budget','identity','stokes_policy','nonlinear_policy','nonlinear_start','anderson_policy','preconditioner_reuse_policy','adaptive_inner_policy') and hasattr(self,k):
            raise TectonicsError('thermal prepared binding is immutable')
        object.__setattr__(self,k,v)
    def __enter__(self):
        if self._closed: raise TectonicsError('thermal plan closed')
        return self
    def __exit__(self,*_): self.close()
    @contextmanager
    def _operation(self,cancel):
        if self._closed or self._active or threading.get_ident()!=self._owner:
            raise TectonicsError('closed/active thermal plan or wrong driving thread')
        self._active=True
        try:
            _cancel(cancel);self._context.verify()
            with _native_lease(): yield
            _cancel(cancel);self._context.verify()
        finally: self._active=False
    def close(self):
        if self._closed:return
        if self._active or threading.get_ident()!=self._owner: raise TectonicsError('close thermal plan on idle driving thread')
        self._closed=True
        try:
            if self._mechanics is not None: self._mechanics.close()
            if self._context is not None: self._context.close()
        finally:
            self._mechanics=None;self._context=None;self._diffusion=None
            self._guard.__exit__(None,None,None)

    def _sum(self,a):
        return float(self._native.sum_compensated(a)) if self.backend=='numba' else math.fsum(a.flat)

    def _mechanics_plan(self,cancel):
        p=self.problem
        if self._mechanics is None:
            if self.nonlinear_policy is None:
                self._mechanics=PreparedStokes2D(p.box,p.rheology,p.scales,policy=self.stokes_policy,budget=self.budget,cancel=cancel)
            else:
                from .variable_stokes_execution import PreparedVariableStokes2D
                self._mechanics=PreparedVariableStokes2D(p.box,p.scales,policy=self.nonlinear_policy,anderson_policy=self.anderson_policy,preconditioner_reuse_policy=self.preconditioner_reuse_policy,adaptive_inner_policy=self.adaptive_inner_policy,budget=self.budget,cancel=cancel)
        return self._mechanics

    def _flow(self,T,C,time,stage,source,cancel,*,initial_guess=None,capture_solution=False):
        rho,_=_check_fields(self.problem,T,C)
        p=self.problem;mechanics=self._mechanics_plan(cancel)
        fx,fz=face_force_from_density(p.box,rho,p.gravity_m_s2,budget=self.budget)
        request=dict(frame_id=p.box.frame_id,epoch_id=p.epoch_id,time_s=time,
            source=source+'; '+stage+' operator-split intermediate, not accepted endpoint',cancel=cancel)
        if self.nonlinear_policy is None:
            flow=mechanics.solve(fx,fz,**request)
        else:
            if initial_guess is not None:request['initial_guess']=initial_guess
            flow=mechanics.solve_rheology(fx,fz,T,p.rheology,**request)
            m=flow.descriptor()
            self._stage_mechanics.append(dict(result_id=flow.result_id,diagnostics=m['diagnostics'],
                nonlinear_iterations=len(m['nonlinear_history']),
                linear_iterations=sum(x['linear_iterations'] for x in m['nonlinear_history'])))
            if self.adaptive_inner_policy is not None:
                self._stage_mechanics[-1]['adaptive_inner']=m['adaptive_inner']
                self._stage_mechanics[-1]['adaptive_inner_history']=m['adaptive_inner_history']
            if self.preconditioner_reuse_policy is not None:
                self._stage_mechanics[-1]['preconditioner_reuse']=m['preconditioner_reuse']
            if self.anderson_policy is not None:
                self._stage_mechanics[-1]['nonlinear_acceleration']=m['nonlinear_acceleration']
            if self.nonlinear_start!='zero-rate':
                self._stage_mechanics[-1]['initial_guess_id']=None if initial_guess is None else initial_guess.guess_id
                self._stage_mechanics[-1]['initial_guess_result_id']=None if initial_guess is None else initial_guess.descriptor()['source_result_id']
        values=(flow.array('u_m_s'),flow.array('w_m_s'),flow.result_id)
        # Preserve the legacy callback protocol; explicitly requested seed capture needs the full result.
        return (*values,flow) if capture_solution else values

    def mechanical_snapshot(self,state,*,source,cancel=None):
        """Solve this plan's exact accepted state without retaining a second plan.

        This is a diagnostic snapshot only: it does not advance time, mutate the
        state or append an RK-stage record.  It deliberately reuses the same
        prepared mechanics owned by the coupled plan so sampling does not double
        retained ILU memory.
        """
        if type(state) is not ThermochemicalState or state.problem.problem_id!=self.problem.problem_id:
            raise TectonicsError('state/problem mismatch; no implicit remapping')
        text(source,'mechanical snapshot provenance')
        if len(source)>2048:raise TectonicsError('mechanical snapshot source too long')
        with self._operation(cancel):
            T=state.array('temperature_k');C=state.array('composition')
            rho,_=_check_fields(self.problem,T,C);p=self.problem
            mechanics=self._mechanics_plan(cancel)
            fx,fz=face_force_from_density(p.box,rho,p.gravity_m_s2,budget=self.budget)
            request=dict(frame_id=p.box.frame_id,epoch_id=p.epoch_id,time_s=state.time_s,source=source,cancel=cancel)
            if self.nonlinear_policy is None:
                return mechanics.solve(fx,fz,**request)
            return mechanics.solve_rheology(fx,fz,T,p.rheology,**request)

    def advance(self,state,dt_s,*,source,extra_heating_w_m3=0.0,velocity=None,cancel=None):
        """One Strang/SSPRK2 step. Source is held fixed over the WHOLE interval.

        velocity=None selects buoyancy feedback and two independently solved stage
        velocities. An explicit PrescribedMACVelocity instead supplies a frozen
        kinematic experiment. Conductivity and rho0*cp are constant; R4.3 can
        select the retained Tosi viscosity/yield law at both mechanical stages.
        Extra heating is nonnegative and added ONCE to the material's internal H;
        this API does not infer shear/adiabatic/latent heating or composition sources.
        The previous-stage1 mode reads its next first-stage seed only from the
        accepted input state, then publishes the new seed with the final state.
        No implicit adaptive steps, order reduction or returned-value clipping.
        """
        if type(state) is not ThermochemicalState or state.problem.problem_id!=self.problem.problem_id:
            raise TectonicsError('state/problem mismatch; no implicit remapping')
        dt=scalar(dt_s,'evolution interval',positive=True);time=state.time_s
        end_time=_endpoint_time(time,dt,self.policy)
        if state.step_index>=self.policy.max_steps: raise TectonicsError('explicit accepted-step envelope exhausted')
        if state.step_index and state.descriptor()['execution_id']!=self.identity:
            raise TectonicsError('continued state source/policy changed; no automatic rebind')
        text(source,'step provenance')
        if len(source)>2048: raise TectonicsError('step source too long')
        b=self.problem.box;shape=(b.nz,b.nx);n=b.nz*b.nx
        if input_shape(extra_heating_w_m3) not in ((),shape): raise TectonicsError('heating must be scalar or cell array')
        if velocity is not None and (type(velocity) is not PrescribedMACVelocity or velocity.box!=b):
            raise TectonicsError('prescribed velocity support differs')
        if velocity is not None and self.adaptive_inner_policy is not None:
            raise TectonicsError('adaptive inner is unused for prescribed velocity')
        if velocity is not None and self.preconditioner_reuse_policy is not None:
            raise TectonicsError('preconditioner reuse is unused for prescribed velocity')
        if velocity is not None and self.anderson_policy is not None:
            raise TectonicsError('Anderson is unused with prescribed velocity')
        if velocity is not None and self.nonlinear_start!='zero-rate':
            raise TectonicsError('explicit nonlinear starting policy cannot be ignored by prescribed velocity')
        # Accepted inputs, source capture, 2 fields, RK candidates/fluxes, spectral
        # scratch, stage solutions, diagnostics and final immutable result copies.
        # Nested Stokes reserves separately. This is admission, not an RSS cap.
        cross=self.nonlinear_start=='previous-stage1'
        previous=state.next_initial_guess if cross else None
        if cross and state.step_index and previous is None:
            raise TectonicsError('cross-step continuation is missing its explicit accepted starting data')
        with self._operation(cancel),self.budget.reserve(1408*n+524288+
                (256*n+131072 if self.nonlinear_start!='zero-rate' else 0)+
                (1024*n+524288 if cross else 0),category='thermochemical-step'):
            self._stage_mechanics=[]
            T=state.array('temperature_k');C=state.array('composition')
            raw=read_array(extra_heating_w_m3,'extra heating',nonnegative=True)
            with np.errstate(over='raise',invalid='raise'):
                try: heating=np.broadcast_to(raw,shape).copy()+self.problem.material.internal_heating_w_m3
                except FloatingPointError as exc: raise TectonicsError('heat source overflow') from exc
            if not np.isfinite(heating).all(): raise TectonicsError('nonfinite heating')
            Q=heating/self.problem.heat_capacity_j_m3_k
            if np.any((Q==0)&(heating!=0)): raise TectonicsError('heat-source rate underflows')
            source_modes=self._diffusion.transform(Q)
            td,bound0=self._diffusion.advance(T,source_modes,dt*.5,cancel)
            q0=np.stack((td,C));_check_fields(self.problem,*q0)
            q1=np.empty_like(q0);q2=np.empty_like(q0)
            fx=np.empty((2,b.nz,b.nx+1));fz=np.empty((2,b.nz+1,b.nx))
            flux=self._native.face_transfers if self.backend=='numba' else _reference_transfers
            update=self._native.euler_update if self.backend=='numba' else None
            boundary=self.problem.boundary
            walls=((boundary.bottom_temperature_k,boundary.top_temperature_k)
                   if boundary.kind=='fixed-top-bottom' else None)
            if velocity is None:
                if self.nonlinear_start in ('rk-stage0','previous-stage1'):
                    request={} if not cross else {'initial_guess':previous}
                    u0,w0,id0,flow0=self._flow(*q0,time,'advection RK stage 0 after first diffusion half',source,cancel,capture_solution=True,**request)
                else:
                    u0,w0,id0=self._flow(*q0,time,'advection RK stage 0 after first diffusion half',source,cancel)
            else:u0,w0,id0=velocity.array('u_m_s'),velocity.array('w_m_s'),velocity.velocity_id
            try:
                cx,cz,cfl0,div0=_courant_arrays(b,u0,w0,dt,self.policy)
            except CourantLimitError as exc:
                raise CourantLimitError('advection RK stage 0: '+str(exc)) from exc
            flux(q0,cx,cz,fx,fz,walls)
            if update is None:q1[:]=q0+(fx[:,:,:-1]-fx[:,:,1:])+(fz[:,:-1,:]-fz[:,1:,:])
            else:update(q0,fx,fz,q1)
            _check_fields(self.problem,*q1);_cancel(cancel)
            meanx=fx*.5;meanz=fz*.5
            if velocity is None:
                guess=None
                if self.nonlinear_start in ('rk-stage0','previous-stage1'):
                    from .variable_stokes_execution import NonlinearStokesGuess
                    guess=NonlinearStokesGuess(flow0,budget=self.budget)
                if cross:
                    u1,w1,id1,flow1=self._flow(*q1,time+dt,'advection RK stage 1 before final diffusion half',source,cancel,initial_guess=guess,capture_solution=True)
                else:
                    u1,w1,id1=self._flow(*q1,time+dt,'advection RK stage 1 before final diffusion half',source,cancel,initial_guess=guess)
                del guess
                if self.nonlinear_start in ('rk-stage0','previous-stage1'):del flow0
            else:u1,w1,id1=u0,w0,id0
            try:
                cx,cz,cfl1,div1=_courant_arrays(b,u1,w1,dt,self.policy)
            except CourantLimitError as exc:
                raise CourantLimitError('advection RK stage 1: '+str(exc)) from exc
            flux(q1,cx,cz,fx,fz,walls)
            if update is None:q2[:]=q1+(fx[:,:,:-1]-fx[:,:,1:])+(fz[:,:-1,:]-fz[:,1:,:])
            else:update(q1,fx,fz,q2)
            _check_fields(self.problem,*q2)
            q2[:]=q0+.5*(q2-q0)
            meanx+=.5*fx;meanz+=.5*fz
            tf,bound1=self._diffusion.advance(q2[0],source_modes,dt*.5,cancel)
            cf=q2[1];_,excursion=_check_fields(self.problem,tf,cf)
            area=(b.width_m/b.nx)*(b.height_m/b.nz);capacity=self.problem.heat_capacity_j_m3_k
            before_heat=self._sum(T)*area*capacity;after_heat=self._sum(tf)*area*capacity
            heat_change=self._sum(tf-T)*area*capacity
            source_heat=self._sum(heating)*area*dt
            bottom_heat=math.fsum((bound0[0],bound1[0]));top_heat=math.fsum((bound0[1],bound1[1]))
            heat_residual=math.fsum((heat_change,-source_heat,bottom_heat,top_heat))
            cbefore=self._sum(C)*area;cafter=self._sum(cf)*area
            composition_change=self._sum(cf-C)*area
            # Complement is derived, never normalised back to sum one after transport.
            residual_ref=max(abs(before_heat),abs(after_heat),abs(source_heat),abs(bottom_heat),abs(top_heat))
            heat_relative=abs(heat_residual)/residual_ref
            # Scale by the constituent inventory, not the whole domain: a tiny
            # represented constituent must not disappear behind a unit-volume gate.
            # Complement round-off comes from storing C rather than a second field.
            cscale=max(self._sum(np.abs(C))*area,self._sum(np.abs(cf))*area)
            composition_relative=abs(composition_change)/cscale if cscale else 0.
            # Independent cell-local advective accounting from RETURNED RK arrays.
            expected_x=meanx[:,:,:-1]-meanx[:,:,1:];expected_z=meanz[:,:-1,:]-meanz[:,1:,:]
            c_local=cf-C-expected_x[1]-expected_z[1]
            t_local=q2[0]-q0[0]-expected_x[0]-expected_z[0]
            local=max(float(np.max(np.abs(c_local))), float(np.max(np.abs(t_local)))/max(1.,float(np.max(np.abs(q0[0])))))
            balances=dict(heat_before_j=before_heat,heat_after_j=after_heat,heat_change_j=heat_change,
                source_heat_j=source_heat,bottom_outward_heat_j=bottom_heat,top_outward_heat_j=top_heat,
                heat_residual_j=heat_residual,heat_relative_residual=heat_relative,
                composition_before_m3=cbefore,composition_after_m3=cafter,composition_change_m3=composition_change,
                complement_before_m3=self._sum(1.-C)*area,complement_after_m3=self._sum(1.-cf)*area,
                composition_relative_residual=composition_relative,advective_local_residual=local,
                composition_bound_excursion=excursion,courant_stage0=cfl0,courant_stage1=cfl1,
                dt_divergence_stage0=div0,dt_divergence_stage1=div1)
            if not all(math.isfinite(v) for v in balances.values()): raise TectonicsError('nonfinite thermochemical balance')
            if max(heat_relative,composition_relative,local)>self.policy.inventory_rtol:
                raise TectonicsError('returned thermochemical fields fail inventory/flux accounting')
            record=dict(method=_METHOD,publication_contract=_PUBLICATION_CONTRACT,
                dt_s=dt,input_time_s=time,source=source,policy=asdict(self.policy),
                velocity_mode=('buoyancy-coupled-variable-viscosity' if self.nonlinear_policy is not None else 'buoyancy-coupled-constant-viscosity') if velocity is None else 'prescribed-frozen-MAC',
                velocity_source=None if velocity is None else velocity.source,
                stage_flow_ids=[id0,id1],heating_sha256=hashlib.sha256(heating.tobytes()).hexdigest(),balances=balances)
            if velocity is None and self.nonlinear_policy is not None:
                record['nonlinear_mechanics']=dict(profile_id=self.problem.rheology.profile_id,
                    policy=asdict(self.nonlinear_policy),stages=list(self._stage_mechanics))
                if self.nonlinear_start!='zero-rate':record['nonlinear_mechanics']['nonlinear_start']=self.nonlinear_start
                if self.anderson_policy is not None:record['nonlinear_mechanics']['anderson_policy']=asdict(self.anderson_policy)
                if self.preconditioner_reuse_policy is not None:record['nonlinear_mechanics']['preconditioner_reuse_policy']=asdict(self.preconditioner_reuse_policy)
                if self.adaptive_inner_policy is not None:record['nonlinear_mechanics']['adaptive_inner_policy']=asdict(self.adaptive_inner_policy)
            next_guess=None
            if cross:
                # Capture only after BOTH stages and all final transport/heat checks pass.
                # This immutable output is not assigned to the plan: failed steps cannot
                # replace the caller's accepted starting data. No recursive flow chain.
                next_guess=NonlinearStokesGuess(flow1,budget=self.budget)
                record['nonlinear_mechanics']['cross_step_start']=dict(
                    input_state_id=state.state_id,
                    input_guess_id=None if previous is None else previous.guess_id,
                    input_stage1_result_id=None if previous is None else previous.descriptor()['source_result_id'],
                    mechanical_plan_id=self._mechanics.identity,output_guess_id=next_guess.guess_id)
                del flow1
            _cancel(cancel)
            final=ThermochemicalState(self.problem,tf,cf,time_s=end_time,source=source,
                parent_id=state.state_id,step_index=state.step_index+1,execution_id=self.identity,
                step_record=record,next_initial_guess=next_guess,budget=self.budget)
            meta=dict(schema='atlas.thermochemical-step.v1',method=_METHOD,record=record,
                before_id=state.state_id,after_id=final.state_id,
                stage_velocity_semantics='operator-split RK intermediate fields, not final-time mechanical solution',
                units='SI, 1 m out-of-plane thickness; advective transfer arrays are dt*u*q/dx or dt*w*q/dz',
                R4_status='IN_PROGRESS',physical_validation=False)
            return ThermochemicalStep(state,final,meta,dict(flux_x_increment=meanx,flux_z_increment=meanz,
                u_stage0_m_s=u0,u_stage1_m_s=u1,w_stage0_m_s=w0,w_stage1_m_s=w1,total_heating_w_m3=heating))


def save_thermochemical_state(state,store,*,budget=None,cancel=None):
    from .storage import ArrayStore
    if type(state) is not ThermochemicalState or not isinstance(store,ArrayStore): raise TectonicsError('state and ArrayStore required')
    policy=select_budget(store._budget if budget is None else budget)
    _cancel(cancel)
    with policy.reserve(3*state.nbytes+65536,category='thermochemical-save'):
        return store.put(state.state_id,{k:state.array(k) for k in state.array_names},state.descriptor(),budget=policy,cancel=cancel)


def load_thermochemical_state(store,state_id,*,budget=None,cancel=None):
    from .storage import ArrayStore
    if not isinstance(store,ArrayStore): raise TectonicsError('ArrayStore required')
    _hex(state_id,'thermal state');_cancel(cancel)
    policy=select_budget(store._budget if budget is None else budget)
    meta=store.metadata(state_id)
    if meta is None: raise TectonicsError('thermochemical snapshot missing')
    # Existing store enforces per-chunk/total decode admission; then this layer
    # admits immutable capture and reconstruction, not a separate persistence engine.
    arrays=store.get(state_id,budget=policy)
    if arrays is None: raise TectonicsError('thermochemical arrays missing')
    with policy.reserve(3*sum(a.nbytes for a in arrays.values())+262144,category='thermochemical-restore'):
        state=ThermochemicalState.restore(meta,arrays,budget=policy)
        if state.state_id!=state_id: raise TectonicsError('thermal snapshot identity mismatch')
        _cancel(cancel)
        return state
