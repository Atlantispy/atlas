#!/usr/bin/env python3
"""Finite R3 numerical/performance evidence; never a full benchmark programme.
SPDX-License-Identifier: AGPL-3.0-only
"""
from pathlib import Path
import json
import math
import os
import platform
import statistics
import sys
import tempfile
import time
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT))
from verify import source_inventory
from atlas_tectonics import (reference_rheology,PreparedRheology,evaluate_rheology,
    advance_memory,DamageLengthScale,PreparedDamageRegularisation,save_law_result,load_law_result)
from atlas_tectonics.execution import ExecutionPolicy
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.storage import ArrayStore,StoreLimits


def main():
    before=source_inventory(ROOT)
    spec=json.loads((ROOT/'cases/physical_closure_r3.json').read_text())
    profile=reference_rheology('bf23-memory')
    # A scalar oracle uses the direct paper equations, not the vector kernel.
    T=np.linspace(0,1,401);depth=np.linspace(0,1,401);rates=np.logspace(-4,8,401);damage=np.linspace(0,20,401)
    actual=evaluate_rheology(profile,T,depth,rates,damage)
    expected=[]
    for t,z,e,d in zip(T,depth,rates,damage):
        strength=(1e6+1.51e7*z)*(1-.9*min(d,10)/10)
        expected.append(min(math.exp(40/(t+1)-20),strength/(2*e)))
    expected=np.asarray(expected);error=float(np.max(abs(actual['viscosity']-expected)/expected))
    if error>1e-14:raise ValueError('independent scalar rheology discrepancy')
    timings=[];identities={};resources=[]
    for case_index,n in enumerate(spec['bounded_measurements']['points']):
        T=np.linspace(0,1,n);rate=np.logspace(-4,8,n);d=np.linspace(0,20,n)
        modes=('threads','serial') if case_index==0 else ('serial','threads')
        for mode in modes:
            budget=WorkBudget(256<<20)
            start=time.perf_counter()
            with PreparedRheology(profile,execution=ExecutionPolicy(mode=mode),budget=budget) as p:
                setup=time.perf_counter()-start
                start=time.perf_counter();result=p.evaluate(T,.5,rate,d);first=time.perf_counter()-start
                samples=[]
                for _ in range(spec['bounded_measurements']['repeats']):
                    start=time.perf_counter();result=p.evaluate(T,.5,rate,d);samples.append(time.perf_counter()-start)
                if n in identities and identities[n]!=result.result_id:raise ValueError('serial/thread identity differs')
                identities[n]=result.result_id
                timings.append({'points':n,'mode':mode,'setup_seconds':setup,'first_complete_call_seconds':first,
                    'reused_complete_call_seconds':samples,'median_reused_seconds':statistics.median(samples),
                    'result_id':result.result_id,'execution':p.execution_statistics,'caller_retained_result_bytes':result.nbytes})
            if budget.reserved_bytes:raise ValueError('law reservations leaked')
            resources.append(budget.statistics())
    refinement=[]
    for n in (24,48,96):
        x=(np.arange(n)+.5)/n;raw=2+np.cos(2*np.pi*x)
        exact=2+np.cos(2*np.pi*x)/(1+(.1*2*np.pi)**2)
        with PreparedDamageRegularisation(DamageLengthScale('fixed-length-evidence',1,.1,n,'authored analytical cosine case')) as p:
            out=p.apply(raw)
        refinement.append({'cells':n,'length_scale':.1,'max_error':float(np.max(abs(out-exact))),
                           'mean_residual':float(out.mean()-raw.mean()),'minimum':float(out.min())})
    ratios=[refinement[i]['max_error']/refinement[i+1]['max_error'] for i in range(2)]
    if not all(3.8<r<4.2 for r in ratios):raise ValueError('regularisation refinement failed')
    with PreparedRheology(profile) as p:
        small=p.advance(np.linspace(0,20,1024),1,np.linspace(0,1,1024),1e-8)
    with tempfile.TemporaryDirectory(prefix='atlas-r3-evidence-') as tmp:
        with ArrayStore(Path(tmp)/'result.sqlite',StoreLimits(4096,8<<20,64<<20)) as store:
            start=time.perf_counter();save_law_result(small,store);write=time.perf_counter()-start
            chunks=store.statistics()['unique_chunks'];save_law_result(small,store)
            if chunks!=store.statistics()['unique_chunks']:raise ValueError('identical record failed deduplication')
            start=time.perf_counter();restored=load_law_result(store,small.result_id);read=time.perf_counter()-start
            exact=all(np.array_equal(restored.array(k),small.array(k)) for k in small.array_names)
            if not exact:raise ValueError('restored memory arrays changed')
            storage={'snapshot_id':small.result_id,'write_seconds':write,'read_seconds':read,'all_arrays_exact':exact,
                     'duplicate_extra_chunks':0,'statistics':store.statistics()}
    storage['budget_after_close']=store._budget.statistics()
    if storage['budget_after_close']['reserved_bytes']:
        raise ValueError('storage reservation leaked after close')
    after=source_inventory(ROOT)
    if before!=after:raise ValueError('source changed during evidence run')
    print(json.dumps({'schema':'atlas.r3-bounded-evidence.v1','status':'PASS_LOCAL_CONSTITUTIVE_CHECKS_ONLY',
        'source_sha256_before':before,'source_sha256_after':after,'source_unchanged':True,
        'runtime':{'python':platform.python_version(),'numpy':np.__version__,'system':platform.system(),
                   'threads':{k:os.environ.get(k) for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS')}},
        'scalar_oracle_relative_error':error,'timings':timings,'resources':resources,
        'regularisation_refinement':refinement,'refinement_error_ratios':ratios,'storage':storage,
        'normal_execution':'native bulk serial; optional owner-profiled auto/threads policy; no automatic physics downgrade',
        'scope':'Finite local-law/length-operator comparison, not full Tosi convection, BF global dynamics, R4, physical acceptance or broad baseline programme',
        'claims':{'physical_validation':False,'coupled_localisation_accepted':False,'universal_speedup':False,
                  'RSS_cap':False,'windows_tested':False,'dependency_installation':False}},indent=2,allow_nan=False))


if __name__=='__main__':main()
