"""Focused item-2/3 comparisons; run explicitly, never during unit verification.

Usage: python -I -B tectonics/tests/measure_copy_transport.py --baseline PATH
PATH is the unmodified tectonics directory at 0590774b.... No network or writes
outside stdout; no world simulation, compression tuning or broad benchmark suite.
"""
from __future__ import annotations
import argparse
import gc
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import statistics
import sys
import time
import tracemalloc

import numpy as np


def load_package(name, directory):
    source = directory / 'src' / 'atlas_tectonics'
    spec = importlib.util.spec_from_file_location(name, source/'__init__.py',
                                                 submodule_search_locations=[str(source)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def allocation(call):
    gc.collect()
    tracemalloc.start()
    result = call()
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    del result
    return {'tracked_peak_bytes': peak, 'tracked_retained_bytes': current}


def comparisons(calls, repeats=5):
    timing = {k: [] for k in calls}
    names = list(calls)
    for call in calls.values(): call()
    for repetition in range(repeats):
        offset = repetition % len(names)
        for name in names[offset:] + names[:offset]:
            start = time.perf_counter_ns()
            result = calls[name]()
            timing[name].append((time.perf_counter_ns()-start)/1e9)
            del result
    return {name:{'median_s':statistics.median(v),'all_seconds':v,
                  **allocation(calls[name])} for name,v in timing.items()}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',type=Path,required=True)
    args=parser.parse_args()
    here=Path(__file__).resolve().parents[1]
    if args.baseline.resolve()==here:parser.error('baseline must be a separate unmodified source tree')
    pinned = {
        '_validation.py':'3e4a7c9c478db52347f80b631e02ed35c5021553',
        'transport.py':'54b223e7c33a75d295df6f74c04ba8c70364ed53',
        'thermal.py':'22fe7a1985cb26b045ccdf7fbca7ce1477a20b4e',
        'resources.py':'af0d36b9a1a4b6e28e6cc3d196c11de030b81094',
        'parameters.py':'98200c694f5e1245b60d491d487514f7e558802d'}
    for name, expected in pinned.items():
        data = (args.baseline/'src/atlas_tectonics'/name).read_bytes()
        actual = hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        if actual != expected:
            parser.error('baseline does not match the reviewed commit: '+name)
    base=load_package('atlas_opt23_baseline',args.baseline)
    now=load_package('atlas_tectonics',here)
    from atlas_tectonics._validation import read_array, frozen
    from atlas_opt23_baseline._validation import array as old_array
    from atlas_tectonics.transport import native_build_info
    report={'scope':'focused copies and transport only; five rotated-order warm repeats',
            'baseline_commit':'0590774b9d59fa9e6c9cba8f5306a3e2b9f6bc40',
            'environment':{'python':platform.python_version(),'numpy':np.__version__,
                           'os':platform.system(),'machine':platform.machine()},
            'limitations':['tracemalloc excludes some native/JIT/library allocations',
                          'not total process RAM, no Windows or world performance claim',
                          'input arrays prepared before timing; calls include validation and publication'],
            'transport':[]}
    h=np.ones(16);u=np.zeros(16)
    start=time.perf_counter()
    now.advect_thickness(h,u,now.PeriodicGrid1D(16,16),.2,backend='numba')
    report['first_native_call_including_import_and_compilation_s']=time.perf_counter()-start
    for n in (256,65536,262144):
        rng=np.random.default_rng(57022)
        h=rng.uniform(0,1000,n);u=rng.uniform(-1,1,n)
        agrid=base.PeriodicGrid1D(n,float(n));bgrid=now.PeriodicGrid1D(n,float(n))
        calls={'baseline':lambda:base.advect_thickness(h,u,agrid,.25),
               'current_reference':lambda:now.advect_thickness(h,u,bgrid,.25,backend='reference'),
               'current_numba':lambda:now.advect_thickness(h,u,bgrid,.25,backend='numba')}
        a=calls['baseline']();b=calls['current_numba']();c=calls['current_reference']()
        same=(a.thickness_m.tobytes()==b.thickness_m.tobytes()==c.thickness_m.tobytes()
              and a.face_flux_m2_s.tobytes()==b.face_flux_m2_s.tobytes()==c.face_flux_m2_s.tobytes()
              and a.solid_volume_per_width_before_m2==b.solid_volume_per_width_before_m2==c.solid_volume_per_width_before_m2
              and a.solid_volume_per_width_after_m2==b.solid_volume_per_width_after_m2==c.solid_volume_per_width_after_m2)
        assert same
        report['transport'].append({'cells':n,'bit_equal_fields_and_sums':same,'paths':comparisons(calls)})
    n=262144
    immutable=frozen(np.linspace(0,10,n))
    report['immutable_read']={'elements':n,'paths':comparisons({
        'baseline_copy':lambda:old_array(immutable,'field'),
        'current_safe_borrow':lambda:read_array(immutable,'field')})}
    # Same opt-in cooling backend on both sides: evaluate copy/workspace changes,
    # not a new backend comparison (item 4 is outside this task).
    before=base.ThermalParameters('synthetic','copy test',300.,1300.,1.)
    after=now.ThermalParameters('synthetic','copy test',300.,1300.,1.)
    cold=base.half_space_temperature(immutable,1,before,backend='scipy')
    new=now.half_space_temperature(immutable,1,after,backend='scipy')
    assert cold.tobytes()==new.tobytes()
    report['cooling_same_backend']={'elements':n,'bit_equal':True,'paths':comparisons({
        'baseline':lambda:base.half_space_temperature(immutable,1,before,backend='scipy'),
        'current':lambda:now.half_space_temperature(immutable,1,after,backend='scipy')})}
    report['native']=native_build_info()
    print(json.dumps(report,indent=2,allow_nan=False))


if __name__=='__main__':main()
