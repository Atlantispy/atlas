"""Focused items 6-8 comparisons. Synthetic arrays; no global performance suite.

Run with native thread environment set before Python starts. Output JSON includes
source identity, actual timings, output comparisons and execution statistics.
No timing threshold is a unit-test requirement. Temporary SQLite stores only.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT/'src'))


def summary(times):
    return {'median_s':statistics.median(times),'min_s':min(times),'max_s':max(times),'samples_s':times}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--baseline',type=Path,required=True)
    args=parser.parse_args()
    import numpy as np
    import scipy
    from atlas_tectonics import Rotation,PeriodicGrid1D,PeriodicFlexure,FlexureParameters,ThermalParameters,half_space_temperature
    from atlas_tectonics._validation import frozen
    from atlas_tectonics.execution import KernelExecutor,ExecutionPolicy
    from atlas_tectonics.reuse import ExecutionContext,PreparedInput,ReuseController,CachePolicy,cached_temperature,cached_flexure,execution_identity
    from atlas_tectonics.storage import ArrayStore,StoreLimits
    thermal=ThermalParameters('synthetic','items6-8 comparison',300.,1300.,1.)
    elastic=FlexureParameters('synthetic','items6-8 comparison',12.,1.,0.,1.,1.)
    rotation=Rotation.from_axis_angle([1.,2.,3.],.7)
    out={'scope':'bounded items 6-8 execution/reuse comparisons; no world forecast',
         'runtime':{'python':platform.python_version(),'numpy':np.__version__,'scipy':scipy.__version__,
                    'system':platform.system(),'machine':platform.machine(),
                    'logical_cpus':getattr(os,'process_cpu_count',os.cpu_count)(),
                    'thread_environment':{k:os.environ.get(k) for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS')}},
         'parallel':[], 'identity':{},'cache':[]}
    for kind in ('cooling','rotation','flexure'):
        for n in (256,65536,262144):
            x=frozen(np.linspace(0,10,n))
            op=PeriodicFlexure(PeriodicGrid1D(n,float(n)),elastic)
            points=frozen(np.resize(x,(n,3)))
            jobs=[(x,1.)]*8 if kind=='cooling' else [points if kind=='rotation' else x]*8
            def call(ex):
                if kind=='cooling':return list(ex.temperatures(jobs,thermal))
                if kind=='rotation':return list(ex.rotations(jobs,rotation))
                return list(ex.flexure(jobs,op))
            modes=['serial','auto','threads']+(['processes'] if n==262144 else [])
            executors={};first={};timings={k:[] for k in modes};stats={}
            try:
                for mode in modes:
                    ex=KernelExecutor(ExecutionPolicy(mode=mode,max_workers=2,max_inflight=4))
                    ex.__enter__();executors[mode]=ex
                    start=time.perf_counter();result=call(ex);first[mode]=time.perf_counter()-start
                    if mode=='serial':expected=[a.tobytes() for a in result]
                    else:
                        for a,b in zip(result,expected):
                            if a.tobytes()!=b:raise AssertionError('execution mode changed output')
                    del result
                for repeat in range(5):
                    order=modes if repeat%2==0 else list(reversed(modes))
                    for mode in order:
                        start=time.perf_counter();result=call(executors[mode]);timings[mode].append(time.perf_counter()-start)
                        for a,b in zip(result,expected):
                            if a.tobytes()!=b:raise AssertionError('execution mode changed output')
                        del result
                stats={k:v.statistics() for k,v in executors.items()}
            finally:
                for ex in reversed(tuple(executors.values())):ex.close()
            out['parallel'].append({'kernel':kind,'elements_per_job':n*(3 if kind=='rotation' else 1),
                                    'job_count':8,'bit_equal':True,'first_call_s':first,
                                    'timings':{k:summary(v) for k,v in timings.items()},'execution':stats})
    # Fresh baseline process: it imports the prior delivered implementation, not
    # a differently named alias inspecting the current package by accident.
    code='''import sys,time,json,statistics
sys.dont_write_bytecode=True
sys.path.insert(0,sys.argv[1])
from atlas_tectonics.reuse import execution_identity
execution_identity('scipy')
t=[]
for _ in range(7):
 s=time.perf_counter();execution_identity('scipy');t.append(time.perf_counter()-s)
print(json.dumps({'median_s':statistics.median(t),'samples_s':t}))
'''
    proc=subprocess.run([sys.executable,'-B','-c',code,str(args.baseline/'src')],text=True,capture_output=True,timeout=30)
    if proc.returncode:raise RuntimeError(proc.stderr)
    out['identity']['previous_fresh']=json.loads(proc.stdout)
    start=time.perf_counter();context=ExecutionContext('scipy');out['identity']['context_initial_s']=time.perf_counter()-start
    fresh=[];verified=[]
    for _ in range(7):
        start=time.perf_counter();execution_identity('scipy');fresh.append(time.perf_counter()-start)
        start=time.perf_counter();context.verify();verified.append(time.perf_counter()-start)
    out['identity']['current_fresh']=summary(fresh)
    out['identity']['current_reused_verify']=summary(verified)
    for n in (256,65536,262144):
        x=frozen(np.linspace(0,10,n));one=frozen(np.array(1.));prepared=PreparedInput(x);age=PreparedInput(one)
        with tempfile.TemporaryDirectory() as d:
            with ArrayStore(Path(d)/'cache.db',StoreLimits(32768,16<<20,64<<20,256<<10)) as store:
                control=ReuseController()
                funcs={'direct':lambda:half_space_temperature(x,one,thermal),
                       'auto':lambda:cached_temperature(x,one,thermal,store=store,controller=control),
                       'always_plain':lambda:cached_temperature(x,one,thermal,store=store,cache_policy=CachePolicy(mode='always')),
                       'always_prepared_context':lambda:cached_temperature(prepared,age,thermal,store=store,
                          context=context,cache_policy=CachePolicy(mode='always'))}
                first={}
                for name,fn in funcs.items():
                    start=time.perf_counter();r=fn();first[name]=time.perf_counter()-start;del r
                times={k:[] for k in funcs}
                for rep in range(5):
                    order=list(funcs) if rep%2==0 else list(reversed(funcs))
                    for name in order:
                        start=time.perf_counter();r=funcs[name]();times[name].append(time.perf_counter()-start)
                        if r.tobytes()!=half_space_temperature(x,one,thermal).tobytes():raise AssertionError('cache changed output')
                out['cache'].append({'elements':n,'first_call_s':first,'timings':{k:summary(v) for k,v in times.items()},
                                     'auto_controller':control.statistics(),'store':store.statistics(),'bit_equal':True})
    out['source_sha256']={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in sorted((ROOT/'src').rglob('*.py'))}
    out['baseline_source_sha256']={p.relative_to(args.baseline).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in sorted((args.baseline/'src').rglob('*.py'))}
    print(json.dumps(out,indent=2))


if __name__=='__main__':main()
