"""Bounded W02 cohort accuracy/cost checks, not a general benchmark programme.

Measure complete calls at the same MUSCL equation/precision. Warm JIT separately;
record tracemalloc alongside estimated reservations, not as total process memory.
This script runs only when explicitly invoked and never changes acceptance limits.
"""
from __future__ import annotations
import hashlib
import json
import math
import platform
from pathlib import Path
import sys
import time
import tracemalloc
import statistics
import tempfile
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from atlas_tectonics import (MaterialCohort,MaterialState,MaterialBoundary,RegionalGrid1D,
    advect_materials,MaterialEvent,apply_material_event,save_material_state,load_material_state)
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.storage import ArrayStore,StoreLimits
from atlas_tectonics.execution import ExecutionPolicy,KernelExecutor


def timed(fn):
    start=time.perf_counter();value=fn();return time.perf_counter()-start,value


def main():
    c,n=4,65536
    cohorts=tuple(MaterialCohort(str(k),'synthetic-rock',f'origin-{k}',-10.*k) for k in range(c))
    x=np.linspace(0,2*np.pi,n);h=np.array([1+.1*np.cos(x+k) for k in range(c)])
    s=MaterialState(RegionalGrid1D(n,float(n)),cohorts,h,time_s=0,epoch_id='synthetic')
    u=np.linspace(-.2,.5,n+1)
    ext=MaterialBoundary('open',{str(k):1. for k in range(c)},'external')
    budget=WorkBudget(64<<20)
    native=lambda:advect_materials(s,u,.2,left=ext,right=ext,budget=budget)
    reference=lambda:advect_materials(s,u,.2,left=ext,right=ext,backend='reference',budget=budget)
    first,a=timed(native);reference()
    samples={'native':[],'reference':[]}
    outputs={}
    for rep in range(5):
        for key,fn in ([('native',native),('reference',reference)] if rep%2==0 else [('reference',reference),('native',native)]):
            elapsed,r=timed(fn);samples[key].append(elapsed);outputs[key]=r
    discrepancy=float(np.max(np.abs(outputs['native'].state.thickness_m-outputs['reference'].state.thickness_m)))
    if not np.allclose(outputs['native'].state.thickness_m,outputs['reference'].state.thickness_m,rtol=1e-12,atol=1e-12):
        raise AssertionError('reference disagreement')
    allocation={}
    for key,fn in [('native',native),('reference',reference)]:
        tracemalloc.start();r=fn();current,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
        allocation[key]={'tracked_peak_bytes':peak,'result_payload_bytes':r.nbytes}
    cases=[]
    for cells in (64,128,256):
        grid=RegionalGrid1D(cells,4.,-2.);dx=grid.spacing_m;xx=-2+(np.arange(cells)+.5)*dx
        def average(x):return 1+.1*(np.sin(2*np.pi*(x+dx/2))-np.sin(2*np.pi*(x-dx/2)))/(2*np.pi*dx)
        st=MaterialState(grid,cohorts[:2],np.array([average(xx),2*average(xx-.3)]),time_s=0,epoch_id='test')
        while st.time_s<.25:
            dt=min(.4*dx,.25-st.time_s)
            b=MaterialBoundary('open',{'0':1+.1*math.cos(2*np.pi*(-2-st.time_s-dt/2)),
                                      '1':2+.2*math.cos(2*np.pi*(-2-st.time_s-dt/2-.3))},'left')
            st=advect_materials(st,np.ones(cells+1),dt,left=b,right=MaterialBoundary('open',None,'right')).state
        wanted=np.array([average(xx-.25),2*average(xx-.55)]);inside=(xx>-1.4)&(xx<1.4)
        cases.append({'cells':cells,'mean_absolute_error_m':float(np.mean(np.abs(st.thickness_m[:,inside]-wanted[:,inside])))})
    parallel={}
    # Complete independent scenarios, not subdivisions of this physical domain.
    for mode in ('serial','auto','threads'):
        values=[]
        with KernelExecutor(ExecutionPolicy(mode=mode,max_workers=2),budget=WorkBudget(256<<20)) as ex:
            for rep in range(5):
                start=time.perf_counter()
                result=list(ex.material_transports([u]*4,s,.2,left=ext,right=ext))
                values.append(time.perf_counter()-start)
                if any(r.state._payload!=a.state._payload for r in result):raise AssertionError('parallel disagreement')
        parallel[mode]={'median_s':statistics.median(values),'samples_s':values}
    with tempfile.TemporaryDirectory() as d:
        with ArrayStore(Path(d)/'test.db',StoreLimits(65536,16<<20,32<<20,decoded_cache_bytes=65536),budget=WorkBudget(64<<20)) as store:
            save_material_state(s,store);initial=store.statistics()
            changed=advect_materials(s,np.zeros(n+1),.2,left=MaterialBoundary('closed'),right=MaterialBoundary('closed')).state
            save_material_state(changed,store);after=store.statistics()
            restored=load_material_state(store,changed.state_id)
            if restored.descriptor()!=changed.descriptor() or restored._payload!=changed._payload:raise AssertionError('restore mismatch')
    data={'scope':'bounded synthetic cohort transport; no geological validation or world forecast',
          'runtime':{'python':platform.python_version(),'numpy':np.__version__,'system':platform.system()},
          'cohorts':c,'cells':n,'scheme':'muscl','first_native_call_s':first,
          'timings':{k:{'median_s':statistics.median(v),'samples_s':v} for k,v in samples.items()},
          'native_reference_max_abs_difference_m':discrepancy,'allocations':allocation,
          'peak_accounted_bytes':budget.peak_reserved_bytes,'budget_bytes':budget.max_bytes,
          'formation_metadata_per_cohort':True,'spatial_refinement':cases,'parallel_scenarios':parallel,
          'snapshot':{'initial':initial,'after_time_only_change':after,'new_chunks':after['unique_chunks']-initial['unique_chunks']},
          'sources':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'src/atlas_tectonics').glob('*.py')}}
    print(json.dumps(data,indent=2,allow_nan=False))


if __name__=='__main__':main()
