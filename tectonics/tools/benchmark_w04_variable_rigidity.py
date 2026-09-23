#!/usr/bin/env python3
"""Matched changing loads: rebuild bounded factors versus request-owned reuse.

Both routes solve the same conservative variable-D equation, use the same mesh
gate and include the first cold preparation. No result-cache hits or relaxed
accuracy. Synthetic SI material choices are timing inputs, not calibration.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import time

for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMBA_NUM_THREADS'):
    os.environ.setdefault(key,'1')
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src')]
import numpy as np
import scipy
from atlas_tectonics import (FlexureParameters,RegionalGrid1D,FlexureBoundary1D,
    RigidityProfile1D,VariableFlexureAccuracy,VariableRigidityFlexure)
from atlas_tectonics.resources import WorkBudget


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    n,calls,repeats=512,12,3
    source='synthetic changing-load timing fixture; not geological calibration'
    grid=RegionalGrid1D(n,400000.)
    params=FlexureParameters('timing-restoring',source,7e10,1000.,.25,3300.,10.)
    boundary=FlexureBoundary1D('continuous','continuous',source)
    te=np.select([np.arange(n)<n//3,np.arange(n)<2*n//3],[1000.,2000.],default=4000.)
    profile=RigidityProfile1D(grid,np.full(n,7e10),te,np.full(n,.25),
        source_id=source,frame_id='synthetic-SI-transect',datum_id='synthetic-depth',epoch_id='fixed',
        far_left=(7e10,1000.,.25),far_right=(7e10,4000.,.25))
    accuracy=VariableFlexureAccuracy(source,1e-3,1e-8,1e-11,1e-14)
    x=(np.arange(n)+.5)/n
    loads=[np.r_[10000.*np.sin(2*np.pi*x+index*.07)+
                   4000.*np.exp(-((x-.35-index*.002)/.05)**2),0.,0.] for index in range(calls)]
    def batch(reuse):
        budget=WorkBudget(256<<20)
        def create(): return VariableRigidityFlexure(profile,params,boundary,accuracy,budget=budget)
        results=[];retained=0
        start=time.perf_counter()
        if reuse:
            with create() as plan:
                for load in loads: results.append(plan.solve(load))
                retained=plan.setup_bytes
        else:
            for load in loads:
                with create() as plan:
                    results.append(plan.solve(load))
                    retained=max(retained,plan.setup_bytes)
        elapsed=time.perf_counter()-start
        if budget.reserved_bytes: raise AssertionError('factor budget was not released')
        return elapsed,results,retained,budget.peak_reserved_bytes
    # One untimed native-library warm-up, not a warm factor cache for either side.
    with VariableRigidityFlexure(profile,params,boundary,accuracy) as plan:
        plan.solve(loads[0])
    times={'rebuild_each_load':[],'reuse_profile_factors':[]}
    retained=peak=0;expected=None
    for repeat in range(repeats):
        order=(False,True) if repeat%2==0 else (True,False)
        for reuse in order:
            elapsed,result,owned,admitted=batch(reuse)
            times['reuse_profile_factors' if reuse else 'rebuild_each_load'].append(elapsed)
            if expected is None: expected=result
            if any(not np.array_equal(a,b) for a,b in zip(result,expected)):
                raise AssertionError('factor reuse changed response, mesh gate or diagnostic bytes')
            retained=max(retained,owned);peak=max(peak,admitted)
    before,after=[statistics.median(times[k]) for k in times]
    paths=[ROOT/'src/atlas_tectonics/variable_flexure.py',Path(__file__)]
    record=dict(status='PASS_BITWISE_ALL_CHANGING_LOAD_RESPONSES_AND_MESH_GATES',
        source=source,cells=n,length_m=grid.length_m,calls_per_repeat=calls,repetitions=repeats,
        python=sys.version.split()[0],numpy=np.__version__,scipy=scipy.__version__,platform=platform.platform(),
        timings_seconds=times,median_rebuild_seconds=before,median_reuse_seconds=after,
        saved_seconds=before-after,saved_percent=100*(before-after)/before,speedup=before/after,
        per_solve_rebuild_seconds=before/calls,per_solve_reuse_seconds=after/calls,
        maximum_retained_factor_bytes=retained,maximum_accounted_peak_bytes=peak,
        accuracy=asdict(accuracy),accepted_subdivisions=[int(a[0,4,3]) for a in expected],
        response_sha256=[hashlib.sha256(a.tobytes()).hexdigest() for a in expected],
        scope='Variable-rigidity 1D kernel, 12 different pressure fields, same profile and accuracy. Both include cold setup; alternating three batches. Includes validation, all refinement solves, polynomial diagnostics, reservations, immutable outputs and close. No result-cache hits, workers, W03 evolution/source-context checks or terrain generation. Not a whole-generator or old-release speed claim. Accounted bytes are not measured RSS.',
        source_sha256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    payload=json.dumps(record,indent=2);print(payload)
    if args.output: args.output.write_text(payload+'\n',encoding='utf-8')


if __name__=='__main__': main()
