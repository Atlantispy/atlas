#!/usr/bin/env python3
"""Finite R4.2 evidence: independent oracles, matched work, state restart.
SPDX-License-Identifier: AGPL-3.0-only
No installation, download, broad baseline programme or general world simulation.
"""
from __future__ import annotations
from dataclasses import replace
import hashlib,json,math,platform,sys,tempfile,time
from pathlib import Path
import numpy as np
from scipy.integrate import solve_ivp
from scipy.linalg import expm
ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests'),str(ROOT)]
from verify import source_inventory
from atlas_tectonics import (PreparedThermochemical2D,save_thermochemical_state,load_thermochemical_state)
from atlas_tectonics.thermochemical import _Diffusion2D
from atlas_tectonics.storage import ArrayStore,StoreLimits
from atlas_tectonics.resources import WorkBudget
from thermochemical_fixtures import (problem,initial,rest,circulation,dense_diffusion,
    rotation_experiment,independent_two_by_two_rhs)


def main():
    before=source_inventory(ROOT);case=json.loads((ROOT/'cases/thermochemical_r4_2.json').read_text())
    results=[]
    for n in case['verification']['performance_grids']:
        p=problem(n);s=initial(p);v=circulation(p);routes={};outputs={}
        for backend in ('numba','reference'):
            budget=WorkBudget(512<<20);t=time.perf_counter()
            with PreparedThermochemical2D(p,backend=backend,budget=budget) as plan:
                setup=time.perf_counter()-t;calls=[]
                for _ in range(case['verification']['performance_repetitions']+1):
                    t=time.perf_counter();r=plan.advance(s,1e-4,source='bounded same-method comparison',velocity=v);calls.append(time.perf_counter()-t)
                outputs[backend]=r
            routes[backend]=dict(setup_seconds=setup,first_complete_seconds=calls[0],reused_complete_seconds=calls[1:],
                median_complete_seconds=float(np.median(calls[1:])),budget=budget.statistics())
        equality={k:bool(np.array_equal(outputs['numba'].state.array(k),outputs['reference'].state.array(k))) for k in ('temperature_k','composition')}
        differences={k:float(np.max(abs(outputs['numba'].state.array(k)-outputs['reference'].state.array(k)))) for k in equality}
        if differences['temperature_k']>1e-11 or differences['composition']>1e-13:raise ValueError('native/reference discrepancy')
        results.append(dict(n=n,velocity='prescribed circulation, NOT a Stokes timing',routes=routes,numeric_arrays_equal=equality,
                            maximum_absolute_differences=differences,identities_equal=outputs['numba'].state.state_id==outputs['reference'].state.state_id,
                            identity_note='Backend/runtime identity differs deliberately; not a cross-backend identical state claim'))
    p=problem(128);s=initial(p);budget=WorkBudget(512<<20);t=time.perf_counter();times=[]
    with PreparedThermochemical2D(p,budget=budget) as plan:
        preparation=time.perf_counter()-t
        for _ in range(4):
            t=time.perf_counter();r=plan.advance(s,1e-4,source='bounded two-stage buoyancy coupling');times.append(time.perf_counter()-t)
    coupled=dict(n=128,setup_seconds=preparation,first_complete_seconds=times[0],reused_complete_seconds=times[1:],
        median_complete_seconds=float(np.median(times[1:])),balances=r.descriptor()['record']['balances'],budget=budget.statistics())
    p=problem(5,4);s=initial(p);D,f=dense_diffusion(p);h=.2+np.arange(20).reshape(4,5)/100
    A=np.zeros((21,21));A[:20,:20]=D;A[:20,20]=f+h.ravel()
    expected=(expm(A*.17)@np.r_[s.array('temperature_k').ravel(),1.])[:20].reshape(4,5)
    d=_Diffusion2D(p);actual,_=d.advance(s.array('temperature_k'),d.transform(h),.17,None)
    dense_error=float(abs(expected-actual).max())
    if dense_error>2e-11:raise ValueError('independent dense diffusion mismatch')
    diffusion=[]
    for n in (8,16,32,64):
        p=problem(n);x,z=np.meshgrid(*p.box.axes());amplitude=np.cos(np.pi*x)*np.sin(np.pi*z)*np.sinc(.5/n)**2
        T=310.-10*z+amplitude;d=_Diffusion2D(p);out,_=d.advance(T,d.transform(np.zeros_like(T)),1.,None)
        expected=310.-10*z+amplitude*np.exp(-2*p.diffusivity_m2_s*np.pi**2)
        diffusion.append(dict(n=n,rms_error=float(np.sqrt(np.mean((out-expected)**2)))))
    rotation=[rotation_experiment(n) for n in (24,48,96,192)]
    p=problem(2,k=.2,contrast=.05,gravity=(1.,-2.));s=initial(p);y=np.r_[s.array('temperature_k').ravel(),s.array('composition').ravel()]
    exact=solve_ivp(lambda t,v:independent_two_by_two_rhs(p,v),(0,1),y,method='DOP853',rtol=3e-13,atol=1e-13)
    if not exact.success:raise ValueError('independent coupled ODE reference failed')
    temporal=[]
    for count in (4,8,16):
        state=s
        with PreparedThermochemical2D(p) as plan:
            for _ in range(count):state=plan.advance(state,1/count,source='independent coupled convergence').state
        v=np.r_[state.array('temperature_k').ravel(),state.array('composition').ravel()]
        temporal.append(dict(steps=count,maximum_error=float(abs(v-exact.y[:,-1]).max())))
    p=problem(16);s=initial(p);budget=WorkBudget(128<<20);v=circulation(p)
    with PreparedThermochemical2D(p,budget=budget) as plan:
        first=plan.advance(s,.02,source='restart first interval',velocity=v).state
        uninterrupted=plan.advance(first,.02,source='restart next interval',velocity=v)
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/'state.sqlite'
        with ArrayStore(path,StoreLimits(4096,16<<20,64<<20),budget=budget) as store:
            save_thermochemical_state(first,store);unique=store.statistics()['unique_chunks']
            save_thermochemical_state(first,store);extra=store.statistics()['unique_chunks']-unique
        with ArrayStore(path,StoreLimits(4096,16<<20,64<<20),budget=budget) as store:restored=load_thermochemical_state(store,first.state_id)
        with PreparedThermochemical2D(restored.problem,budget=budget) as plan:continued=plan.advance(restored,.02,source='restart next interval',velocity=v)
    restart=dict(state_arrays_exact=all(np.array_equal(first.array(k),restored.array(k)) for k in ('temperature_k','composition')),
        state_id_exact=first.state_id==restored.state_id,continued_step_id_exact=uninterrupted.result_id==continued.result_id,
        duplicate_additional_chunks=extra,budget=budget.statistics())
    if not all((restart['state_arrays_exact'],restart['state_id_exact'],restart['continued_step_id_exact'],extra==0,budget.reserved_bytes==0)):
        raise ValueError('restart/dedup/resource check failed')
    after=source_inventory(ROOT)
    if after!=before:raise ValueError('source changed during bounded evidence')
    report=dict(schema='atlas.r4-2-bounded-evidence.v1',status='PASS_REGISTERED_THERMOCHEMICAL_COMPONENTS',
        source_sha256_before=before,source_sha256_after=after,source_unchanged=True,
        runtime=dict(python=platform.python_version(),numpy=np.__version__,scipy=__import__('scipy').__version__,platform=platform.system()),
        matched_transport_comparisons=results,coupled_complete_step=coupled,independent_diffusion_max_error_k=dense_error,
        diffusion_spatial_refinement=diffusion,compact_rotation_refinement=rotation,coupled_temporal_refinement=temporal,
        restart=restart,claims=dict(R4_complete=False,Tosi_benchmark_reproduced=False,physical_validation=False,Windows_tested=False,
        universal_speedup=False,RSS_cap=False),scope='Finite independent numerical and matched-work checks; not an isolated cold-process timing or whole-planet forecast')
    print(json.dumps(report,indent=2,allow_nan=False));return 0

if __name__=='__main__':raise SystemExit(main())
