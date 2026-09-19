#!/usr/bin/env python3
"""Bounded R4.1 mechanical checks and matched direct/iterative timings.
SPDX-License-Identifier: AGPL-3.0-only
No thermal time integration, reference acquisition, installer or broad benchmark.
JSON stdout is new evidence, never a replacement for a historical report.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
import time
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from verify import source_inventory
from atlas_tectonics import (PreparedStokes2D,StokesSolvePolicy,reference_rheology,
                             save_stokes_solution,load_stokes_solution)
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.storage import ArrayStore,StoreLimits
from stokes_fixtures import unit_box,unit_scales,request,analytic,errors


def main():
    before=source_inventory(ROOT)
    case=json.loads((ROOT/'cases/stokes_r4_1.json').read_text())
    budget=WorkBudget(256<<20);rows=[];numerical=[];paired={}
    for n in case['analytical_cases']['main_parameters']['square_grids']:
        b=unit_box(n);values=analytic(b)
        with PreparedStokes2D(b,reference_rheology('constant'),unit_scales(),budget=budget) as p:
            result=p.solve(*values[:2],**request(b))
        numerical.append({'cells_per_axis':n,**errors(result,values),
                          'diagnostics':result.descriptor()['diagnostics'],'result_id':result.result_id})
    for n in case['bounded_execution']['comparisons']+case['bounded_execution']['larger_iterative_grids']:
        b=unit_box(n);rng=np.random.default_rng(1909+n)
        fx=rng.normal(size=(n,n-1));fz=rng.normal(size=(n-1,n))
        for method in (('minres','direct') if n in case['bounded_execution']['comparisons'] else ('minres',)):
            local=WorkBudget(256<<20)
            start=time.perf_counter()
            p=PreparedStokes2D(b,reference_rheology('constant'),unit_scales(),policy=StokesSolvePolicy(method=method),budget=local)
            setup=time.perf_counter()-start
            times=[]
            try:
                for j in range(case['bounded_execution']['repeats']+1):
                    start=time.perf_counter();result=p.solve(fx,fz,**request(b));times.append(time.perf_counter()-start)
                held=local.reserved_bytes
                if n in case['bounded_execution']['comparisons']:
                    paired[(n,method)]=result
                rows.append({'cells_per_axis':n,'unknowns':b.unknowns,'method':method,
                    'setup_s':setup,'first_complete_s':times[0],'reused_complete_s':times[1:],
                    'reused_median_s':float(np.median(times[1:])),
                    'iterations':result.descriptor()['iterations'],
                    'diagnostics':result.descriptor()['diagnostics'],'result_id':result.result_id,
                    'held_plan_bytes':held,'peak_admitted_bytes':local.peak_reserved_bytes})
            finally:p.close()
            rows[-1]['remaining_reserved_bytes']=local.reserved_bytes
    comparisons=[]
    for n in case['bounded_execution']['comparisons']:
        a=paired[(n,'minres')];b=paired[(n,'direct')]
        comparisons.append({'cells_per_axis':n,'max_absolute_difference':{
            k:float(np.max(np.abs(a.array(k)-b.array(k)))) for k in ('u_m_s','w_m_s','pressure_pa')},
            'expect_bit_identity':False,'meaning':'independent linear solvers, same discretisation; numerical agreement not identical arithmetic'})
    saved=paired[(case['bounded_execution']['comparisons'][-1],'minres')]
    with tempfile.TemporaryDirectory() as td:
        with ArrayStore(Path(td)/'stokes.db',StoreLimits(4096,8<<20,64<<20),budget=budget) as store:
            start=time.perf_counter();save_stokes_solution(saved,store);write_s=time.perf_counter()-start
            chunks=store.statistics()['unique_chunks'];save_stokes_solution(saved,store)
            extra=store.statistics()['unique_chunks']-chunks
        with ArrayStore(Path(td)/'stokes.db',StoreLimits(4096,8<<20,64<<20),budget=budget) as store:
            start=time.perf_counter();restored=load_stokes_solution(store,saved.result_id);read_s=time.perf_counter()-start
            exact=all(np.array_equal(restored.array(k),saved.array(k)) for k in saved.array_names)
            storage=store.statistics()
    if not exact or extra!=0:raise ValueError('steady restoration/deduplication failed')
    for n in numerical:
        if n['diagnostics']['momentum_linf']>case['default_policy']['momentum_tolerance']:
            raise ValueError('mechanical numerical gate failed')
    after=source_inventory(ROOT)
    if before!=after:raise ValueError('source changed during R4.1 comparison')
    record={'schema':'atlas.r4-1-bounded-evidence.v1','status':'PASS_CONSTANT_VISCOSITY_MECHANICAL_COMPONENT_ONLY',
        'R4_status':'IN_PROGRESS','R4_complete':False,'source_sha256_before':before,'source_sha256_after':after,
        'source_unchanged':True,'runtime':{'python':platform.python_version(),'numpy':np.__version__,
            'scipy':__import__('scipy').__version__,'platform':platform.system(),
            'thread_environment':{k:os.environ.get(k) for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS')}},
        'continuum_refinement':numerical,'direct_iterative':comparisons,'timings':rows,
        'storage':{'saved_array_identity_exact':exact,'extra_chunks_on_duplicate_write':extra,
                   'write_s':write_s,'cold_reopen_restore_s':read_s,'statistics':storage},
        'work_budget':budget.statistics(),
        'claims':{'thermal_evolution':False,'variable_viscosity':False,'Tosi_convection_reproduced':False,
            'physical_validation':False,'production_ready':False,'RSS_cap':False,'universal_speedup':False,
            'Windows_or_macOS_tested':False}}
    print(json.dumps(record,indent=2,allow_nan=False))
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except (ValueError,OSError,ImportError) as e:
        print(json.dumps({'status':'FAIL_OR_BLOCKED_R4_1','error':str(e)}),file=sys.stderr)
        raise SystemExit(2)
