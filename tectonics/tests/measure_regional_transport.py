"""Bounded W02 accuracy/cost comparison, not a world benchmark or performance gate.

Run with native thread counts set before interpreter launch. All data are synthetic
and all persistent results live in temporary directories. This script installs
nothing and never changes prior reference evidence or physical tolerances.
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
import gc, hashlib, json, math, platform, statistics, time, tracemalloc
import numpy as np
from atlas_tectonics import RegionalGrid1D,TransportBoundary,advect_regional
from atlas_tectonics._validation import snapshot
from atlas_tectonics.regional import regional_work_bytes,pack_regional_result
from atlas_tectonics.execution import KernelExecutor,ExecutionPolicy
from atlas_tectonics.resources import WorkBudget
from test_regional_transport import cell_average_bump


def timed(call,repeats=5):
    times=[]
    for _ in range(repeats):
        start=time.perf_counter();value=call();times.append(time.perf_counter()-start)
        del value
    return dict(median_s=statistics.median(times),min_s=min(times),max_s=max(times),repeats=repeats)


def main():
    record={'scope':'synthetic fixed-density regional advection; not geological validation',
            'runtime':{'python':platform.python_version(),'numpy':np.__version__,'platform':platform.system()},
            'spatial_refinement':{},'single_step':{},'independent_batches':{}}
    boundary=TransportBoundary('open',.2)
    h=np.ones(8);u=np.ones(9);g=RegionalGrid1D(8,8)
    t=time.perf_counter();advect_regional(h,u,g,.2,left=boundary,right=boundary)
    record['first_native_call_s']=time.perf_counter()-t
    # Fixed target and nominal CFL policy are chosen before collecting results.
    # Upwind uses its larger admissible fraction; MUSCL its half-size allowance.
    target=.002;record['cell_mean_L1_target_m']=target
    for scheme,cfl in [('upwind',.8),('muscl',.4)]:
        rows=[]
        for n in (32,64,128,256,512,1024,2048):
            grid=RegionalGrid1D(n,1);initial=snapshot(cell_average_bump(n),'initial')
            vel=snapshot(np.ones(n+1),'velocity');expected=cell_average_bump(n,.1)
            steps=math.ceil(.1*n/cfl);dt=.1/steps
            def evolve():
                state=initial
                for _ in range(steps):
                    state=advect_regional(state,vel,grid,dt,left=boundary,right=boundary,scheme=scheme).thickness_m
                return state
            actual=evolve()
            row=dict(cells=n,steps=steps,cfl=dt*n,L1_m=float(np.mean(abs(actual-expected))),
                     Linf_m=float(np.max(abs(actual-expected))),workspace_allowance_bytes=regional_work_bytes(n,scheme=scheme))
            row.update(timed(evolve,3));rows.append(row)
        record['spatial_refinement'][scheme]=rows
    for n in (65536,262144):
        grid=RegionalGrid1D(n,float(n));x=np.linspace(0,4,n);h=snapshot(.5+.2*np.sin(x),'h')
        vel=snapshot(np.linspace(.2,.4,n+1),'u')
        calls={name:(lambda name=name:advect_regional(h,vel,grid,.5,left=boundary,right=boundary,
                scheme='muscl',backend=name)) for name in ('reference','numba')}
        # Both implementations warmed before alternating paired measurements.
        values={k:f() for k,f in calls.items()}
        equal=pack_regional_result(values['reference']).tobytes()==pack_regional_result(values['numba']).tobytes()
        del values
        times={k:[] for k in calls}
        for repeat in range(5):
            for name in (('reference','numba') if repeat%2==0 else ('numba','reference')):
                start=time.perf_counter();value=calls[name]();times[name].append(time.perf_counter()-start);del value
        rows={k:dict(median_s=statistics.median(v),min_s=min(v),max_s=max(v)) for k,v in times.items()}
        for k,f in calls.items():
            gc.collect();tracemalloc.start();value=f();_,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
            rows[k]['tracked_peak_bytes']=peak;del value
        record['single_step'][str(n)]={'paths':rows,'bit_equal':equal,'samples':n}
    # Same complete independent domains, not disconnected chunks of one domain.
    n=262144;grid=RegionalGrid1D(n,float(n));h=snapshot(np.linspace(.5,2,n),'h');u=snapshot(np.full(n+1,.25),'u')
    expected=advect_regional(h,u,grid,.5,left=boundary,right=boundary)
    for mode in ('serial','auto'):
        with KernelExecutor(ExecutionPolicy(mode=mode,max_workers=2,max_inflight=2),budget=WorkBudget(256<<20)) as executor:
            def run():
                for result in executor.regional_transports([(h,u)]*4,grid,.5,left=boundary,right=boundary):
                    if pack_regional_result(result).tobytes()!=pack_regional_result(expected).tobytes():raise AssertionError('parallel mismatch')
            run();info=timed(run,5);info['executor']=executor.statistics();record['independent_batches'][mode]=info
    record['source_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'src/atlas_tectonics').glob('*.py'))}
    print(json.dumps(record,indent=2,allow_nan=False))

if __name__=='__main__':main()
