#!/usr/bin/env python3
"""Finite registered R4.3 equations, nonlinear convergence, reuse and storage.
SPDX-License-Identifier: AGPL-3.0-only
No global simulation, dependency installation, source acquisition or R4.4 benchmark.
"""
from pathlib import Path
from dataclasses import replace
import hashlib,json,platform,sys,tempfile,time
import numpy as np
from scipy.integrate import solve_ivp
ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True;sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests'),str(ROOT)]
from verify import source_inventory
from atlas_tectonics import (PreparedVariableStokes2D,NonlinearStokesPolicy,PreparedThermochemical2D,
    save_variable_stokes_solution,load_variable_stokes_solution,save_thermochemical_state,load_thermochemical_state)
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.storage import ArrayStore,StoreLimits
from variable_stokes_fixtures import (unit_box,unit_scales,request,analytic_variable,refinement,
    forcing,two_cell_solution,independent_two_cell_amplitude,coupled_problem,independent_nonlinear_two_cell_rhs)
from thermochemical_fixtures import initial


def main():
    before=source_inventory(ROOT);case=json.loads((ROOT/'cases/variable_stokes_r4_3.json').read_text());spec=case['bounded_measurement']
    fixed=[];nonlinear=[];repeats=spec['repetitions']
    for n in spec['prescribed_grids']:
        b=unit_box(n);a=analytic_variable(b);budget=WorkBudget(512<<20);clock=time.perf_counter()
        with PreparedVariableStokes2D(b,unit_scales(),budget=budget) as p:
            setup=time.perf_counter()-clock;calls=[];rids=[]
            for _ in range(repeats+1):
                clock=time.perf_counter();r=p.solve(*a[:4],**request(b));calls.append(time.perf_counter()-clock);rids.append(r.result_id)
            stats=p.statistics();diagnostics=r.descriptor()['diagnostics']
        if len(set(rids))!=1 or stats['factor_builds']!=1:raise ValueError('fixed coefficient reuse failed')
        clock=time.perf_counter()
        with PreparedVariableStokes2D(b,unit_scales(),budget=budget) as p:r=p.solve(*a[:4],**request(b))
        fresh=time.perf_counter()-clock
        fixed.append(dict(n=n,unknowns=b.unknowns,setup_seconds=setup,first_complete_seconds=calls[0],
            reused_complete_seconds=calls[1:],median_complete_seconds=float(np.median(calls[1:])),fresh_setup_solve_close_seconds=fresh,
            statistics=stats,diagnostics=diagnostics,resource_admission=budget.statistics(),identical_repeat_ids=True))
    for n in spec['nonlinear_grids']:
        b,s,fx,fz,T,profile=forcing(n);budget=WorkBudget(512<<20);clock=time.perf_counter()
        with PreparedVariableStokes2D(b,s,budget=budget) as p:
            setup=time.perf_counter()-clock;calls=[];ids=[]
            for _ in range(repeats+1):
                clock=time.perf_counter();r=p.solve_rheology(fx,fz,T,profile,**request(b));calls.append(time.perf_counter()-clock);ids.append(r.result_id)
            metadata=r.descriptor();stats=p.statistics()
        if len(set(ids))!=1:raise ValueError('nonlinear history affected result identity')
        nonlinear.append(dict(n=n,setup_seconds=setup,first_complete_seconds=calls[0],reused_complete_seconds=calls[1:],
            median_complete_seconds=float(np.median(calls[1:])),outer_iterations=len(metadata['nonlinear_history']),
            linear_iterations=sum(v['linear_iterations'] for v in metadata['nonlinear_history']),history=metadata['nonlinear_history'],
            diagnostics=metadata['diagnostics'],statistics=stats,budget=budget.statistics()))
    b,s,fx,fz,T,profile=forcing(spec['linear_comparison_grid']);routes={};answers={}
    for method in ('direct','gmres'):
        clock=time.perf_counter();calls=[]
        with PreparedVariableStokes2D(b,s,policy=NonlinearStokesPolicy(method=method)) as p:
            setup=time.perf_counter()-clock
            for _ in range(repeats+1):
                clock=time.perf_counter();r=p.solve_rheology(fx,fz,T,profile,**request(b));calls.append(time.perf_counter()-clock)
        routes[method]=dict(setup_seconds=setup,first_complete_seconds=calls[0],reused_complete_seconds=calls[1:],median_complete_seconds=float(np.median(calls[1:])))
        answers[method]=r
    differences={k:float(np.max(abs(answers['direct'].array(k)-answers['gmres'].array(k)))) for k in ('u_m_s','w_m_s','pressure_pa')}
    for k in differences:
        scale=max(1.,float(np.max(abs(answers['direct'].array(k)))))
        if differences[k]>2e-8*scale:raise ValueError('nonlinear direct/iterative mismatch')
    refinement_rows=[refinement(n) for n in (8,16,32)]
    roots=[]
    for force in (.01,1.,5.,-1.):
        r=two_cell_solution(force);exact=independent_two_cell_amplitude(force,1.6)
        error=abs(float(r.array('u_m_s')[0,1])/exact-1)
        if error>3e-9:raise ValueError('independent scalar-root mismatch')
        roots.append(dict(force=force,exact_amplitude=exact,computed=float(r.array('u_m_s')[0,1]),relative_error=error))
    p=coupled_problem(2);s=initial(p);y=np.r_[s.array('temperature_k').ravel(),s.array('composition').ravel()]
    oracle=solve_ivp(lambda t,y:independent_nonlinear_two_cell_rhs(p,y),(0.,.5),y,method='DOP853',rtol=1e-12,atol=1e-13)
    if not oracle.success:raise ValueError('independent ODE failed')
    temporal=[]
    for n in (2,4,8):
        st=s
        with PreparedThermochemical2D(p) as plan:
            for _ in range(n):st=plan.advance(st,.5/n,source='independent nonlinear temporal reference').state
        v=np.r_[st.array('temperature_k').ravel(),st.array('composition').ravel()]
        temporal.append(dict(steps=n,maximum_error=float(np.max(abs(v-oracle.y[:,-1])))))
    p=coupled_problem(spec['coupled_grid']);s=initial(p);budget=WorkBudget(512<<20);clock=time.perf_counter();calls=[]
    with PreparedThermochemical2D(p,budget=budget) as plan:
        setup=time.perf_counter()-clock
        for _ in range(repeats+1):
            clock=time.perf_counter();first=plan.advance(s,spec['coupled_dt_s'],source='bounded two-stage variable solve');calls.append(time.perf_counter()-clock)
        continued=plan.advance(first.state,spec['coupled_dt_s'],source='second interval').state
    coupled=dict(n=p.box.nx,setup_seconds=setup,first_complete_seconds=calls[0],reused_complete_seconds=calls[1:],
        median_complete_seconds=float(np.median(calls[1:])),record=first.descriptor()['record'],budget=budget.statistics())
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/'snapshots.sqlite'
        with ArrayStore(path,StoreLimits(4096,16<<20,64<<20)) as store:
            save_variable_stokes_solution(answers['gmres'],store);save_thermochemical_state(first.state,store)
            chunks=store.statistics()['unique_chunks'];save_thermochemical_state(first.state,store)
            save_variable_stokes_solution(answers['gmres'],store)
            if store.statistics()['unique_chunks']!=chunks:raise ValueError('duplicate chunks')
        with ArrayStore(path,StoreLimits(4096,16<<20,64<<20)) as store:
            restored=load_thermochemical_state(store,first.state.state_id);mechanics=load_variable_stokes_solution(store,answers['gmres'].result_id)
        with PreparedThermochemical2D(restored.problem) as plan:resumed=plan.advance(restored,spec['coupled_dt_s'],source='second interval').state
        if resumed.state_id!=continued.state_id:raise ValueError('nonlinear restart mismatch')
        for k in mechanics.array_names:
            if not np.array_equal(mechanics.array(k),answers['gmres'].array(k)):raise ValueError('mechanical restore mismatch')
    after=source_inventory(ROOT)
    if before!=after:raise ValueError('source changed during R4.3 check')
    report=dict(schema='atlas.r4-3-bounded-evidence.v1',status='PASS_REGISTERED_R4_3_NUMERICAL_COMPONENTS',
        source_sha256_before=before,source_sha256_after=after,source_unchanged=True,
        runtime=dict(python=platform.python_version(),numpy=np.__version__,platform=platform.system()),
        prescribed_coefficients=fixed,nonlinear_coefficients=nonlinear,direct_iterative_comparison=dict(routes=routes,maximum_absolute_differences=differences),
        continuum_refinement=refinement_rows,independent_scalar_roots=roots,nonlinear_temporal_refinement=temporal,coupled_step=coupled,
        storage=dict(restored_mechanical_arrays_exact=True,continued_state_exact=True,duplicate_additional_chunks=0),
        R4_status='IN_PROGRESS',R4_complete=False,full_convection_benchmark=False,physical_validation=False,
        claims=dict(RSS_cap=False,universal_speedup=False,isolated_cold_process_timing=False,Windows_macOS=False))
    print(json.dumps(report,indent=2,allow_nan=False));return 0

if __name__=='__main__':raise SystemExit(main())
