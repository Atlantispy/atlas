"""Bounded items 4/5 comparisons only; no general benchmark, installer or speed gate.

Run with --baseline pointing at the previous optimised-defaults tectonics folder.
Pin BLAS/OpenMP thread settings before starting the interpreter. Output is JSON.
"""
from __future__ import annotations
import argparse
import gc
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
import tracemalloc

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
BASE_HASHES = {
    'thermal.py': '9c5cc33af2fbeaf10acf41939b5041f09aa70cad7f564ad221afd577a7670228',
    'kinematics.py': 'aeabeb7e200b9094c5eda7651707d1e60576bbef6bc4f9abf1306b8b9f623e25',
    'flexure.py': 'fec98cb525be273f85cdb37808ebfac44e66c478c066481cf28382b80893a98c',
    '_validation.py': '7d84d32f0a7e8b1d0d3e5292fc8b0080bc2282c249bcfda117c02139742cfb4c',
}


def load_package(name, path):
    directory=path/'src/atlas_tectonics'
    spec=importlib.util.spec_from_file_location(name,directory/'__init__.py',submodule_search_locations=[str(directory)])
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    return module


def compare(calls, repeats=5):
    # Warm imports and data paths separately; do not count profiling in timings.
    outputs={name:fn() for name,fn in calls.items()}
    names=list(calls);reference=outputs[names[0]]
    checks={name:{'bit_equal':a.tobytes()==reference.tobytes(),
                  'max_abs_difference':float(np.max(np.abs(a-reference)))} for name,a in outputs.items()}
    samples={name:[] for name in calls}
    for i in range(repeats):
        for name in (names if i%2==0 else list(reversed(names))):
            started=time.perf_counter();value=calls[name]();samples[name].append(time.perf_counter()-started);del value
    measured={}
    for name,fn in calls.items():
        gc.collect();tracemalloc.start();value=fn();_,peak=tracemalloc.get_traced_memory();tracemalloc.stop();del value
        measured[name]={'median_s':statistics.median(samples[name]),'min_s':min(samples[name]),'max_s':max(samples[name]),
                        'samples_s':samples[name],'tracked_peak_bytes':peak,**checks[name]}
    return measured


def first_use(path, backend, repeats=3):
    code='''import sys,time,json
sys.path.insert(0,sys.argv[1])
start=time.perf_counter()
import numpy as np
from atlas_tectonics import ThermalParameters,half_space_temperature
imported=time.perf_counter()
p=ThermalParameters('synthetic','first-use measurement',300.,1300.,1.)
d=np.linspace(0,10,65536)
a=time.perf_counter();half_space_temperature(d,1.,p,backend=sys.argv[2]);b=time.perf_counter()
half_space_temperature(d,1.,p,backend=sys.argv[2]);c=time.perf_counter()
print(json.dumps({'import_s':imported-start,'first_call_s':b-a,'second_call_s':c-b,'total_first_use_s':b-start}))
'''
    out=[]
    for _ in range(repeats):
        proc=subprocess.run([sys.executable,'-I','-B','-c',code,str(path/'src'),backend],capture_output=True,text=True,timeout=30)
        if proc.returncode:raise RuntimeError(proc.stderr)
        out.append(json.loads(proc.stdout))
    return out


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--baseline',type=Path,required=True);args=parser.parse_args()
    for name,expected in BASE_HASHES.items():
        actual=hashlib.sha256((args.baseline/'src/atlas_tectonics'/name).read_bytes()).hexdigest()
        if actual!=expected:raise ValueError('wrong prior optimised-defaults baseline: '+name)
    old=load_package('atlas45_old',args.baseline);new=load_package('atlas45_new',ROOT)
    import scipy
    records={'scope':'items 4/5 only: synthetic kernels; no whole-world or parallel-worker benchmark',
             'baseline':'optimised-defaults delivery after remote 0590774b',
             'runtime':{'python':platform.python_version(),'numpy':np.__version__,'scipy':scipy.__version__,
                        'os':platform.system(),'machine':platform.machine(),
                        'threads':{k:os.environ.get(k) for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS')}},
             'warming':'warm-import alternating-order timings; first-use subprocesses reported separately; OS cache not flushed',
             'memory':'tracemalloc incremental tracked allocations, not total RSS/native-library peaks',
             'cooling':{},'rotations':{},'flexure':{}}
    op=old.ThermalParameters('synthetic','test only',300.,1300.,1.)
    np_=new.ThermalParameters('synthetic','test only',300.,1300.,1.)
    from atlas45_new._validation import frozen
    shapes={
       'scalar':(1.,1.),
       'vector_256':(frozen(np.linspace(0,10,256)),1.),
       'vector_65536':(frozen(np.linspace(0,10,65536)),1.),
       'vector_262144':(frozen(np.linspace(0,10,262144)),1.),
       'depths_1024_ages_64':(frozen(np.linspace(0,10,1024)[:,None]),frozen(np.linspace(0,4,64)[None,:])),
       'varying_age_65536':(frozen(np.linspace(0,10,65536)),frozen(np.linspace(0,4,65536))),
       'strided_256x256':(np.arange(256*512.,dtype=float).reshape(256,512)[:,::2],frozen(np.linspace(0,4,256)[None,:])),
    }
    for name,(d,t) in shapes.items():
        records['cooling'][name]=compare({'baseline_scipy':lambda:old.half_space_temperature(d,t,op),
            'current_scipy':lambda:new.half_space_temperature(d,t,np_),
            'current_reference':lambda:new.half_space_temperature(d,t,np_,backend='reference')})
    old_rotation=old.Rotation.from_axis_angle([1,2,3],.7);new_rotation=new.Rotation.from_axis_angle([1,2,3],.7)
    for count in (1,256,65536,262144):
        points=frozen(np.random.default_rng(44).normal(size=(count,3)))
        records['rotations'][str(count)]=compare({'baseline_cross':lambda:old_rotation.apply(points),
           'current_matrix':lambda:new_rotation.apply(points),
           'current_reference':lambda:new_rotation.apply(points,backend='reference')})
    small=frozen(np.arange(768.).reshape(256,3))
    records['rotation_build_and_apply']=compare({
        'baseline':lambda:old.Rotation.from_axis_angle([1,2,3],.7).apply(small),
        'current':lambda:new.Rotation.from_axis_angle([1,2,3],.7).apply(small)})
    old_e=old.FlexureParameters('synthetic','test only',12.,1.,0.,1.,1.)
    new_e=new.FlexureParameters('synthetic','test only',12.,1.,0.,1.,1.)
    for rows,cells in ((1,65536),(32,1024),(256,1024),(64,8192),(11,257)):
        a=old.PeriodicFlexure(old.PeriodicGrid1D(cells,float(cells)),old_e)
        b=new.PeriodicFlexure(new.PeriodicGrid1D(cells,float(cells)),new_e)
        loads=frozen(np.random.default_rng(77).normal(size=(rows,cells)))
        calls={'baseline_batch':lambda:a.solve(loads),
               'current_default':lambda:b.solve(loads),
               'current_batch8':lambda:b.solve(loads,batch_loads=8),
               'current_batch64':lambda:b.solve(loads,batch_loads=64),
               'baseline_separate':lambda:np.stack([a.solve(row) for row in loads])}
        records['flexure'][f'{rows}x{cells}']=compare(calls)
    # Check granularity choices on a repeated broadcast without running a tuning search.
    d=frozen(np.linspace(0,10,2048)[:,None]);t=frozen(np.linspace(0,4,128)[None,:])
    records['cooling_batch_choices']=compare({str(s):(lambda size=s:new.half_space_temperature(d,t,np_,batch_elements=size)) for s in (8192,65536,262144)})
    records['cooling_first_use']={'scipy':first_use(ROOT,'scipy'),'reference':first_use(ROOT,'reference')}
    print(json.dumps(records,indent=2,allow_nan=False))

if __name__=='__main__':main()
