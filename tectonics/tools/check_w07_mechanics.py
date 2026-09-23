#!/usr/bin/env python3
"""Bounded W07 acceptance and matched-output measurements; NEW JSON report only.

SPDX-License-Identifier: AGPL-3.0-only
Runs frozen synthetic steady cases, never an evolving or geological simulation.
Every independent failure is recorded. No threshold, grid or solver fallback is
selected after observing a result. Imports/process startup are outside timing;
the public workflow comparisons include setup, inputs, solves, output and close.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import platform
import statistics
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'tests'), str(ROOT/'tools')]
FROZEN_DESIGN_SHA256 = '1748c9e2bd43f71ad0ce65fb9d68343d3f1379570f1b2b74882b85fa2c644378'
BUDGET_BYTES = 128*1024**2
SIDES = ('left', 'right', 'bottom', 'top')
TIMING_GRID = 32  # Fixed before the run; never selected from observed timings/errors.
FE_RESOLVED_RECORDS = ('exact/couette/FE', 'exact/hydrostatic_traction/FE')


class SourceChanged(RuntimeError):
    pass


def _sources():
    paths = [*sorted((ROOT/'src/atlas_tectonics').rglob('*.py')),
             ROOT/'tools/w07_fe_reference.py', Path(__file__), ROOT/'tests/w07_reference_fields.py',
             ROOT/'tests/test_regional_stokes_core.py', ROOT/'tests/test_regional_execution.py',
             ROOT/'tests/stokes_fixtures.py', ROOT/'tests/test_stokes_r4_1.py',
             ROOT/'tests/test_variable_stokes_r4_3.py', ROOT/'cases/w07_mechanics.json',
             ROOT/'cases/stokes_r4_1.json', ROOT/'cases/variable_stokes_r4_3.json',
             ROOT/'docs/W07_REGIONAL_MECHANICS.md']
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def _jsonable(value):
    import numpy as np
    if isinstance(value, dict):
        return {str(k):_jsonable(v) for k,v in value.items()}
    if isinstance(value, (tuple,list)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    return value


class Recorder:
    def __init__(self, report, sources):
        self.report, self.sources = report, sources

    def verify(self):
        if _sources() != self.sources:
            raise SourceChanged('source/case/script bytes changed during run; no acceptance or timing claim is valid')

    def call(self, name, function):
        self.verify()
        row = {'name':name}
        self.report['checks'].append(row)
        started = time.perf_counter()
        try:
            value = function()
            self.verify()
            row.update(status='PASS', result=_jsonable(value))
            return value
        except SourceChanged:
            row.update(status='FAIL_SOURCE_CHANGED', error=traceback.format_exc(limit=4))
            raise
        except Exception as exc:
            row.update(status='FAIL', error_type=type(exc).__name__, error=str(exc),
                       traceback=traceback.format_exc(limit=5))
            return None
        finally:
            row['elapsed_seconds'] = time.perf_counter()-started

    def gate(self, name, condition, evidence):
        row = dict(name=name,status='PASS' if condition else 'FAIL',result=_jsonable(evidence))
        self.report['checks'].append(row)
        return bool(condition)


def _gauge(case):
    return None if case in ('couette','hydrostatic_traction') else 0.


def _rectangular_fields(x,z):
    """Retained analytic R4.1 rectangular forcing; no discrete operator in RHS."""
    import numpy as np
    kx,kz=np.pi/3.,np.pi
    u=.05*kz*np.sin(kx*x)*np.cos(kz*z)
    w=-.05*kx*np.cos(kx*x)*np.sin(kz*z)
    p=.3*np.cos(2*kx*x)*np.cos(kz*z)
    fx=(kx*kx+kz*kz)*u-.6*kx*np.sin(2*kx*x)*np.cos(kz*z)
    fz=(kx*kx+kz*kz)*w-.3*kz*np.cos(2*kx*x)*np.sin(kz*z)
    return u,w,p,fx,fz


def _case(case):
    import w07_reference_fields as oracle
    if case == 'free_slip_rectangular':
        return 3.,1.,_rectangular_fields,oracle.boundaries('free_slip')
    width,height=oracle.dimensions(case)
    return width,height,lambda x,z:oracle.fields(case,x,z),oracle.boundaries(case)


def _inputs(case,nx,nz,amplitude=1.):
    import numpy as np
    from atlas_tectonics.regional_stokes import boundary_coordinates
    width,height,fields,boundaries=_case(case)
    # The rectangular free-slip normal velocities are exactly zero; do not use
    # the unit-box helper's nonzero interior trace on the x=3 boundary.
    if case == 'free_slip_rectangular':
        boundaries={side:{component:(kind,0.) for component,(kind,_) in parts.items()}
                    for side,parts in boundaries.items()}
    xu,zu=np.meshgrid(np.arange(nx+1)*width/nx,(np.arange(nz)+.5)*height/nz)
    xw,zw=np.meshgrid((np.arange(nx)+.5)*width/nx,np.arange(nz+1)*height/nz)
    fu=amplitude*np.asarray(fields(xu,zu)[3]); fw=amplitude*np.asarray(fields(xw,zw)[4])
    sampled={}
    for side,parts in boundaries.items():
        sampled[side]={}
        for component,(kind,value) in parts.items():
            x,z=boundary_coordinates(nx,nz,width,height,side,component)
            values=value(x,z) if callable(value) else np.full(x.shape,value)
            sampled[side][component]=(kind,amplitude*np.asarray(values,dtype=float))
    return width,height,fu,fw,sampled


def _interpolate_mac(raw,width,height,points):
    """Bilinear face fields with actual solved boundary traces, not edge padding.

    Cell-centre pressure has no independent Dirichlet trace. Its explicitly
    selected first-order polynomial continuation uses the outer two centres.
    This reproduces affine hydrostatic pressure up to the physical boundary.
    """
    import numpy as np
    from scipy.interpolate import RegularGridInterpolator
    u,w,p=raw['u'],raw['w'],raw['p']
    nz,nx=p.shape
    xc=(np.arange(nx)+.5)*width/nx; zc=(np.arange(nz)+.5)*height/nz
    xf=np.arange(nx+1)*width/nx; zf=np.arange(nz+1)*height/nz
    traces=raw['boundary_velocities']
    bottom=np.asarray(traces['bottom']['u']); top=np.asarray(traces['top']['u'])
    left=np.asarray(traces['left']['w']); right=np.asarray(traces['right']['w'])
    if bottom.shape!=(nx+1,) or top.shape!=(nx+1,) or left.shape!=(nz+1,) or right.shape!=(nz+1,):
        raise ValueError('MAC solved tangential traces do not occupy declared physical boundary vertices')
    u_full=np.vstack((bottom,u,top)); w_full=np.column_stack((left,w,right))
    zextended=np.r_[0.,zc,height]; xextended=np.r_[0.,xc,width]
    target=points[:,[1,0]]
    return dict(u=RegularGridInterpolator((zextended,xf),u_full,bounds_error=True)(target),
                w=RegularGridInterpolator((zf,xextended),w_full,bounds_error=True)(target),
                p=RegularGridInterpolator((zc,xc),p,bounds_error=False,fill_value=None)(target))


def _common_errors(case,points,weights,sampled):
    import numpy as np
    import w07_reference_fields as oracle
    sampled={key:np.asarray(value).copy() for key,value in sampled.items() if key in ('u','w','p')}
    removed=0.
    if _gauge(case) is not None:
        target=oracle.fields(case,points[:,0],points[:,1])[2]
        removed=float(np.dot(weights,sampled['p']-target)/sum(weights))
        sampled['p']-=removed
    result=oracle.continuum_errors(case,points,weights,sampled)
    result['pressure_mean_offset_removed']=removed
    result['pressure_policy']='weighted common-domain gauge alignment' if _gauge(case) is not None else 'physical pressure; no offset removed'
    exact=oracle.fields(case,points[:,0],points[:,1])
    result['field_max_error']=float(max(np.max(abs(sampled[name]-target))
                                      for name,target in zip(('u','w','p'),exact[:3])))
    return result


def _diagnostic_gates(recorder,name,kind,diagnostics,gauge):
    if kind=='MAC':
        limits={'momentum_residual':1e-9,'divergence_residual':1e-10,
                'normalised_work_residual':1e-9,'linear_residual':1e-12,
                'boundary_velocity_residual':1e-12,'corner_trace_residual':1e-12,
                'rigid_constraint_residual':1e-10}
        if gauge is not None:
            limits['pressure_gauge_residual']=1e-12
        for key,limit in limits.items():
            value=diagnostics.get(key)
            recorder.gate(name+'/'+key,value is not None and abs(value)<=limit,
                          dict(value=value,maximum=limit))
        recorder.gate(name+'/all_core_gates',diagnostics.get('gates_passed') is True,
                      dict(gates_passed=diagnostics.get('gates_passed')))
    else:
        # FE continuity is the complete P1 weak equation, including each
        # element's constant mass test. It is not pointwise div(v)=0.
        for key,limit in (('weak_continuity_scaled_max',1e-10),('scaled_work_residual',1e-9)):
            recorder.gate(name+'/'+key,abs(diagnostics[key])<=limit,dict(value=diagnostics[key],maximum=limit))
        if gauge is not None:
            recorder.gate(name+'/gauge',abs(diagnostics['gauge_error'])<=1e-12,
                          dict(value=diagnostics['gauge_error'],maximum=1e-12))


def _native_errors(case,width,height,raw,amplitude=1.):
    """Frozen staggered face/cell norm, with half-volume outer normal faces.

    This is the B02 core acceptance norm, distinct from the cross-method common
    quadrature norm. Analytic pressure retains its continuum mean-zero datum;
    no sampled-mean subtraction hides its finite-grid quadrature error.
    """
    import numpy as np
    _,_,fields,_=_case(case)
    nz,nx=raw['p'].shape
    xu,zu=np.meshgrid(np.arange(nx+1)*width/nx,(np.arange(nz)+.5)*height/nz)
    xw,zw=np.meshgrid((np.arange(nx)+.5)*width/nx,np.arange(nz+1)*height/nz)
    xp,zp=np.meshgrid((np.arange(nx)+.5)*width/nx,(np.arange(nz)+.5)*height/nz)
    ue=amplitude*fields(xu,zu)[0]; we=amplitude*fields(xw,zw)[1]; pe=amplitude*fields(xp,zp)[2]
    qu,qw=np.ones_like(ue),np.ones_like(we)
    qu[:,[0,-1]]=.5; qw[[0,-1],:]=.5
    volume=width*height/(nx*nz)
    eu=float(np.sqrt(np.sum(qu*(raw['u']-ue)**2)*volume))
    ew=float(np.sqrt(np.sum(qw*(raw['w']-we)**2)*volume))
    ep=float(np.sqrt(np.sum((raw['p']-pe)**2)*volume))
    vnorm=float(np.sqrt((np.sum(qu*ue**2)+np.sum(qw*we**2))*volume))
    pnorm=float(np.sqrt(np.sum(pe**2)*volume))
    return dict(u_l2=eu,w_l2=ew,p_l2=ep,velocity_relative_l2=float(np.hypot(eu,ew)/vnorm),
                p_relative_l2=ep/pnorm,pressure_mean_offset_removed=0.,
                pressure_policy='analytic continuum mean-zero datum; no discrete mean alignment')


@contextmanager
def _mac_plan(owner,case,nx,nz):
    from atlas_tectonics.regional_stokes import prepare_mac
    width,height,fu,fw,boundaries=_inputs(case,nx,nz)
    upper=3*nx*nz+4*(nx+nz)+16
    allowance=8*1024**2+5120*upper+262144
    with owner.reserve(allowance,category='w07-independent-mac'):
        plan=prepare_mac(nx,nz,width,height,1.,boundaries,pressure_mean=_gauge(case),
                         method='gmres',linear_rtol=1e-12,max_iterations=1200,restart=60)
        try:
            yield plan,(width,height,fu,fw,boundaries)
        finally:
            if hasattr(plan,'close'):
                plan.close()


def _mac_case(owner,case,nx,nz,*,common=True):
    import numpy as np
    import w07_reference_fields as oracle
    started=time.perf_counter()
    with _mac_plan(owner,case,nx,nz) as (plan,inputs):
        width,height,fu,fw,boundaries=inputs
        setup=time.perf_counter()-started
        begin=time.perf_counter(); raw=plan.solve(fu,fw,boundaries=boundaries); complete=time.perf_counter()-begin
        record=dict(method='MAC',case=case,nx=nx,nz=nz,setup_seconds=setup,
                    complete_solve_seconds=complete,core_timings=raw.get('timings',{}),
                    unknown_count=plan.unknowns,velocity_unknown_count=plan.velocity_unknowns,
                    pressure_unknown_count=plan.pressure_unknowns,
                    full_velocity_trace_count=plan.full_velocity_unknowns,
                    matrix_nnz=plan.matrix_nnz,retained_core_bytes=plan.retained_nbytes,
                    diagnostics=raw['diagnostics'],iterations=raw.get('iterations'))
        if common:
            points,weights=oracle.quadrature(width,height,cells=32,order=3)
            sampled=_interpolate_mac(raw,width,height,points)
            record['common_errors']=_common_errors(case,points,weights,sampled)
        if case=='vortex':
            record['native_errors']=_native_errors(case,width,height,raw)
        if case in ('free_slip','free_slip_rectangular'):
            _,_,fields,_=_case(case)
            xu,zu=np.meshgrid(np.arange(nx+1)*width/nx,(np.arange(nz)+.5)*height/nz)
            xw,zw=np.meshgrid((np.arange(nx)+.5)*width/nx,np.arange(nz+1)*height/nz)
            xp,zp=np.meshgrid((np.arange(nx)+.5)*width/nx,(np.arange(nz)+.5)*height/nz)
            record['retained_native_rms']=dict(
                u_l2=float(np.sqrt(np.mean((raw['u'][:,1:-1]-fields(xu,zu)[0][:,1:-1])**2))),
                w_l2=float(np.sqrt(np.mean((raw['w'][1:-1,:]-fields(xw,zw)[1][1:-1,:])**2))),
                p_l2=float(np.sqrt(np.mean((raw['p']-fields(xp,zp)[2])**2))))
        return record


def _fe_case(owner,case,nx,nz):
    import w07_reference_fields as oracle
    from w07_fe_reference import prepare_reference
    width,height,fields,boundaries=_case(case)
    # The shared continuum oracle is vectorised, including its constant fields.
    # The FE boundary callback contract evaluates one point and requires a real
    # scalar, not a zero-dimensional ndarray. This adapter changes no values.
    boundaries={side:{component:(kind,(lambda x,z,value=value:float(value(x,z)))
                                  if callable(value) else value)
                      for component,(kind,value) in parts.items()}
                for side,parts in boundaries.items()}
    count=2*(2*nx+1)*(2*nz+1)+3*nx*nz+int(_gauge(case) is not None)
    allowance=64*count*count+4096*count+8192*nx*nz+65536
    with owner.reserve(allowance,category='w07-independent-fe'):
        started=time.perf_counter()
        plan=prepare_reference(nx,nz,width,height,1.,boundaries,pressure_mean=_gauge(case),max_work_bytes=BUDGET_BYTES)
        setup=time.perf_counter()-started
        begin=time.perf_counter(); result=plan.solve(lambda x,z:fields(x,z)[3:5]); complete=time.perf_counter()-begin
        points,weights=oracle.quadrature(width,height,cells=32,order=3)
        errors=_common_errors(case,points,weights,result.evaluate(points))
        return dict(method='Q2/P1-disc',case=case,nx=nx,nz=nz,setup_seconds=setup,
                    complete_solve_seconds=complete,unknown_count=result.unknown_count,
                    solved_unknown_count=result.solved_unknown_count,projected_work_bytes=result.projected_work_bytes,
                    diagnostics=dict(result.diagnostics),common_errors=errors,
                    core_timings=dict(assembly_seconds=result.setup_seconds,factor_seconds=result.factor_seconds,
                        load_seconds=result.load_seconds,solve_seconds=result.solve_seconds,
                        diagnostics_seconds=result.diagnostics_seconds))


def _refinement(recorder,name,records,keys,minimum,maximum=None,field='common_errors',strict=False):
    complete=all(record is not None for record in records)
    if not complete:
        recorder.gate(name,False,dict(reason='one or more required grid results failed'))
        return
    for key in keys:
        values=[record[field][key] for record in records]
        ratios=[values[i]/values[i+1] if values[i+1] else None for i in range(len(values)-1)]
        passed=all(r is not None and (r>minimum if strict else r>=minimum) and
                   (maximum is None or (r<maximum if strict else r<=maximum)) for r in ratios)
        recorder.gate(name+'/'+key,passed,dict(errors=values,ratios=ratios,minimum=minimum,maximum=maximum,strict=strict))


def _fe_controls(recorder,owner,cases):
    for case in cases:
        name='exact/'+case+'/FE'
        row=recorder.call(name,lambda case=case:_fe_case(owner,case,4,4))
        if row is not None:
            _diagnostic_gates(recorder,name,'Q2/P1-disc',row['diagnostics'],_gauge(case))
            recorder.gate(name+'/field',row['common_errors']['field_max_error']<=1e-9,row['common_errors'])


def acceptance(recorder,owner):
    method_rows=[]
    macro={}
    for kind,grids,runner in (('MAC',(4,8,16),_mac_case),('Q2/P1-disc',(2,4,8),_fe_case)):
        for n in grids:
            name=f'comparison/B02/{kind}/{n}'
            row=recorder.call(name,lambda n=n,runner=runner:runner(owner,'vortex',n,n))
            if row is not None:
                method_rows.append(row)
                _diagnostic_gates(recorder,name,kind,row['diagnostics'],0.)
                if kind=='MAC': macro[n]=row
    recorder.report['method_comparison']=dict(rows=method_rows,
        sampling='common32x32 cells,3-point tensor Gauss; velocity bilinear MAC with actual wall traces; pressure linear extrapolation',
        interpretation='single-run components are not speedups; compare accepted physical error and output, not equal grid or raw DOFs')
    records=[]
    for n in (16,32,64):
        row=macro.get(n)
        if row is None:
            row=recorder.call(f'acceptance/B02/MAC/{n}',lambda n=n:_mac_case(owner,'vortex',n,n,common=False))
            if row is not None:_diagnostic_gates(recorder,f'acceptance/B02/{n}','MAC',row['diagnostics'],0.)
        records.append(row)
    _refinement(recorder,'B02/frozen-refinement',records,('velocity_relative_l2','p_relative_l2'),3.2,field='native_errors')
    for key in ('velocity_relative_l2','p_relative_l2'):
        value=None if records[-1] is None else records[-1]['native_errors'][key]
        recorder.gate('B02/finest/'+key,value is not None and value<=.01,dict(value=value,maximum=.01))
    for case in ('extension','translated_extension','couette','hydrostatic','hydrostatic_traction','rotation'):
        nx,nz=(8,4) if 'extension' in case else (8,8)
        name='exact/'+case+'/MAC'
        row=recorder.call(name,lambda case=case,nx=nx,nz=nz:_mac_case(owner,case,nx,nz))
        if row is not None:
            _diagnostic_gates(recorder,name,'MAC',row['diagnostics'],_gauge(case))
            recorder.gate(name+'/field',row['common_errors']['field_max_error']<=1e-9,
                          dict(value=row['common_errors']['field_max_error'],maximum=1e-9))
    # These are common-output comparison controls, not another execution of the
    # seven FE unit tests or the root's public-wrapper test suite.
    _fe_controls(recorder,owner,('extension','couette','hydrostatic_traction'))
    for case in ('free_slip','free_slip_rectangular'):
        rows=[]
        for n in (8,16,32):
            nx=n if case=='free_slip' else 2*n
            name=f'B01/{case}/{nx}x{n}'
            row=recorder.call(name,lambda nx=nx,n=n,case=case:_mac_case(owner,case,nx,n,common=False))
            rows.append(row)
            if row is not None:_diagnostic_gates(recorder,name,'MAC',row['diagnostics'],0.)
        if case=='free_slip':
            _refinement(recorder,'B01/retained-square',rows,('u_l2','w_l2','p_l2'),3.7,4.6,'retained_native_rms',strict=True)
            for key,limit in (('u_l2',8e-5),('w_l2',8e-5),('p_l2',5e-4)):
                value=None if rows[-1] is None else rows[-1]['retained_native_rms'][key]
                recorder.gate('B01/retained-finest/'+key,value is not None and value<limit,dict(value=value,maximum=limit))
        else:
            _refinement(recorder,'B01/retained-rectangular-last-ratio',rows[-2:],('u_l2','w_l2','p_l2'),3.7,
                        field='retained_native_rms',strict=True)
    recorder.report['deferred_scope']=['B01 variable-viscosity derivative case belongs to Step3; old thresholds retained',
        'No ALE, material transport, yielding, true surface, empirical validation or full W07 acceptance']


def _snapshot_hash(snapshot):
    return hashlib.sha256(b''.join(name.encode()+snapshot.array(name).tobytes()
                                  for name in sorted(snapshot.array_names))).hexdigest()


def _public_sequence(owner,mode):
    from atlas_tectonics.regional_execution import PreparedRegionalStokes2D, RegionalMechanicsScales
    nx=nz=TIMING_GRID
    amplitudes=(.8,1.,1.2) if mode.endswith('changed_rhs') else (1.,1.,1.)
    repeated=mode.startswith('prepared') or mode.startswith('verified')
    setup_times=[]; solve_times=[]; load_times=[]; outputs=[]; identities=[]; hits=[]; errors=[]
    def new_plan():
        _,_,_,_,boundary=_inputs('vortex',nx,nz)
        pattern={side:{c:condition[0] for c,condition in parts.items()} for side,parts in boundary.items()}
        start=time.perf_counter()
        plan=PreparedRegionalStokes2D(nx,nz,1.,1.,1.,pattern,
            scales=RegionalMechanicsScales(1.,1.),frame_id='w07-synthetic-x-right-z-up',
            vertical_datum='w07-synthetic-z-zero',material_source='w07-synthetic-unit-viscosity',
            physical_mean_pressure_pa=0.,method='gmres',budget=owner)
        setup_times.append(time.perf_counter()-start)
        return plan
    plan=None
    started=time.perf_counter()
    previous=None
    try:
        if repeated:plan=new_plan()
        for amplitude in amplitudes:
            if not repeated:plan=new_plan()
            begin=time.perf_counter(); _,_,fu,fw,boundary=_inputs('vortex',nx,nz,amplitude)
            values={side:{c:condition[1] for c,condition in parts.items()} for side,parts in boundary.items()}
            load_times.append(time.perf_counter()-begin)
            begin=time.perf_counter()
            result=plan.solve(fu,fw,values,frame_id='w07-synthetic-x-right-z-up',epoch_id='w07-synthetic-steady',
                time_s=0.,force_source='w07-vortex-amplitude-'+repr(amplitude),boundary_source='w07-closed-no-slip')
            solve_times.append(time.perf_counter()-begin)
            if mode.startswith('verified') and previous is not None and result is not previous:
                raise AssertionError('identical latest request did not return the verified same snapshot')
            outputs.append(_snapshot_hash(result)); identities.append(result.result_id); previous=result
            raw={key:result.array(name) for key,name in
                 (('u','u_m_s'),('w','w_m_s'),('p','dynamic_pressure_pa'))}
            errors.append(_native_errors('vortex',1.,1.,raw,amplitude))
            hits.append(plan.statistics()['latest_result_hits'])
            if not repeated:plan.close();plan=None
    finally:
        if plan is not None:plan.close()
    return dict(end_to_end_seconds=time.perf_counter()-started,setup_seconds=setup_times,
        input_seconds=load_times,complete_request_seconds=solve_times,output_sha256=outputs,result_ids=identities,
        latest_result_hits=hits,amplitudes=amplitudes,nx=nx,nz=nz,native_errors=errors,
        accuracy_qualified=all(e['velocity_relative_l2']<=.01 and e['p_relative_l2']<=.01 for e in errors))


def timings(recorder,owner):
    modes=('cold_changed_rhs','prepared_changed_rhs','cold_identical_rhs','verified_identical_rhs')
    samples={mode:[] for mode in modes}
    order=[]
    for repeat in range(3):
        rotation=modes[repeat:]+modes[:repeat]
        order.append(rotation)
        for mode in rotation:
            value=recorder.call(f'timing/{repeat+1}/{mode}',lambda mode=mode:_public_sequence(owner,mode))
            if value is not None:
                samples[mode].append(value)
                recorder.gate(f'timing/{repeat+1}/{mode}/accuracy',value['accuracy_qualified'],
                    dict(native_errors=value['native_errors'],relative_l2_maximum=.01))
    summary=dict(rotating_order=order,raw=samples,comparison_scope='Each route includes setup, three requested outputs and close; imports excluded. Immutable output hashing is included equally.')
    for baseline,actual in ((modes[0],modes[1]),(modes[2],modes[3])):
        left,right=samples[baseline],samples[actual]
        complete=len(left)==len(right)==3
        parity=complete and all(a['output_sha256']==b['output_sha256'] for a,b in zip(left,right))
        accuracy=complete and all(row['accuracy_qualified'] for row in left+right)
        recorder.gate('timing/parity/'+actual,parity,dict(complete=complete,exact_output_bytes=parity))
        if not parity or not accuracy:
            summary[actual]=dict(status='NO_SAVING_CLAIM',reason='missing matched execution, exact output parity, or accepted accuracy')
            continue
        l=[row['end_to_end_seconds'] for row in left]; r=[row['end_to_end_seconds'] for row in right]
        lm,rm=statistics.median(l),statistics.median(r)
        summary[actual]=dict(status='MATCHED_OUTPUTS',baseline_seconds=l,candidate_seconds=r,
            baseline_median_seconds=lm,candidate_median_seconds=rm,saved_seconds=lm-rm,
            saved_percent=100*(lm-rm)/lm,baseline_first_minus_median_seconds=l[0]-lm,
            candidate_first_minus_median_seconds=r[0]-rm,
            physical_scope=f'B02 synthetic{TIMING_GRID}x{TIMING_GRID} MAC; this is workflow reuse, not a cross-method or whole-generator speedup')
    recorder.report['workflow_timing']=summary


def _bind_supplement(path,sources):
    """Bind only the two known callback-adapter failures; do not repin inputs."""
    encoded=path.read_bytes()
    prior=json.loads(encoded)
    key=Path(__file__).relative_to(ROOT).as_posix()
    previous=prior['source_sha256']
    unchanged={name:digest for name,digest in sources.items() if name!=key}
    if unchanged!={name:digest for name,digest in previous.items() if name!=key}:
        raise SourceChanged('supplement requires unchanged production, oracle, FE and case identities')
    failed={row['name']:row for row in prior['checks'] if row['status']!='PASS'}
    if set(failed)!=set(FE_RESOLVED_RECORDS) or any(
            row.get('error_type')!='FEReferenceError' or
            row.get('error')!='boundary value must be a finite real scalar'
            for row in failed.values()):
        raise ValueError('prior report does not contain exactly the two known FE scalar-adapter failures')
    return dict(parent_report=str(path.resolve()),parent_report_sha256=hashlib.sha256(encoded).hexdigest(),
                prior_runner_sha256=previous[key],new_runner_sha256=sources[key],
                unchanged_nonrunner_source_sha256=unchanged,
                targeted_prior_failed_records=list(FE_RESOLVED_RECORDS),
                interpretation='Two-control correction only; previous successes/timings are not rerun or relabelled')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',required=True,type=Path)
    options=parser.add_mutually_exclusive_group()
    options.add_argument('--acceptance-only',action='store_true')
    options.add_argument('--timing-only',action='store_true')
    options.add_argument('--fe-controls-only',action='store_true')
    parser.add_argument('--prior-report',type=Path,help='Required only for the two-control correction supplement')
    args=parser.parse_args()
    if args.fe_controls_only != (args.prior_report is not None):
        parser.error('--fe-controls-only requires --prior-report, which is not used in other modes')
    report=dict(schema='atlas.w07-basic-mechanics-acceptance.v1',source_status='WORKING NON-CANON',
        status='INCOMPLETE',checks=[],command=sys.argv,scope='bounded constant Newtonian steady regional mechanics',
        runtime=dict(python=sys.version,platform=platform.platform()),
        resource_policy=dict(work_budget_bytes=BUDGET_BYTES,numerical_threads=1,OS_RSS_cap=False,
                             automatic_fallback=False),mode='fe-controls-only' if args.fe_controls_only else
            'timing-only' if args.timing_only else 'acceptance-only' if args.acceptance_only else 'combined')
    # Exclusive creation happens before work: an existing report is never
    # overwritten, and any caught failure/interrupt has a designated evidence file.
    with args.report.open('x',encoding='utf-8') as output:
        try:
            sources=_sources(); report['source_sha256']=sources
            if args.fe_controls_only:
                report['supplement_binding']=_bind_supplement(args.prior_report,sources)
            case=json.loads((ROOT/'cases/w07_mechanics.json').read_text(encoding='utf-8'))
            if (case['frozen_design']['sha256']!=FROZEN_DESIGN_SHA256 or
                    sources['docs/W07_REGIONAL_MECHANICS.md']!=FROZEN_DESIGN_SHA256):
                raise SourceChanged('frozen W07 design binding differs; no automatic repin')
            import numpy as np
            import scipy
            from atlas_tectonics.resources import WorkBudget
            from atlas_tectonics.stokes_execution import _native_lease
            from threadpoolctl import threadpool_info
            report['runtime'].update(numpy=np.__version__,scipy=scipy.__version__)
            recorder=Recorder(report,sources)
            owner=WorkBudget(BUDGET_BYTES)
            try:
                with _native_lease(),owner.reserve(8*1024**2,category='w07-acceptance-caller'):
                    pools=[{key:p.get(key) for key in ('internal_api','prefix','num_threads')} for p in threadpool_info()]
                    report['runtime']['native_threadpools']=pools
                    if any(p['num_threads']!=1 for p in pools):
                        raise RuntimeError('managed native lease did not establish one numerical thread')
                    recorder.verify()
                    if args.fe_controls_only:
                        _fe_controls(recorder,owner,('couette','hydrostatic_traction'))
                        report['resolved_prior_failed_records']=[name for name in FE_RESOLVED_RECORDS
                            if all(row['status']=='PASS' for row in report['checks']
                                   if row['name']==name or row['name'].startswith(name+'/'))]
                        parent_sha=hashlib.sha256(args.prior_report.read_bytes()).hexdigest()
                        if parent_sha!=report['supplement_binding']['parent_report_sha256']:
                            raise SourceChanged('parent evidence report changed during correction run')
                    else:
                        if not args.timing_only:acceptance(recorder,owner)
                        if not args.acceptance_only:timings(recorder,owner)
                    recorder.verify()
            finally:
                report['budget']=owner.statistics()
            if report['budget']['reserved_bytes']:
                recorder.gate('resource-cleanup',False,report['budget'])
            failures=[row['name'] for row in report['checks'] if row['status']!='PASS']
            report['failures']=failures
            suffix='FE_CONTROLS_ONLY' if args.fe_controls_only else 'TIMING_ONLY' if args.timing_only else 'ACCEPTANCE_ONLY' if args.acceptance_only else 'BOUNDED_W07_STEP2'
            report['status']=('PASS_' if not failures else 'FAIL_')+suffix
        except BaseException as exc:
            report['status']='FAIL_BOUNDED_W07_STEP2'
            report['fatal_error']=dict(type=type(exc).__name__,message=str(exc),traceback=traceback.format_exc(limit=8))
        json.dump(_jsonable(report),output,indent=2,allow_nan=False)
        output.write('\n');output.flush()
    print(json.dumps(dict(status=report['status'],checks=len(report['checks']),
                         failures=report.get('failures',[]),fatal=report.get('fatal_error'),report=str(args.report))))
    return 0 if report['status'].startswith('PASS') else 1


if __name__=='__main__':
    raise SystemExit(main())
