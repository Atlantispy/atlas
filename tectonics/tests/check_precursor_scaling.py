#!/usr/bin/env python3
"""Bounded R2 indexing/scheduling evidence, not a planetary benchmark.

Measures complete matched requests (admission, validation, output construction),
first calls separately from pool reuse, and index construction within validation.
Input construction is reported separately. Numerical arrays/identities must match;
timing is descriptive and never an acceptance gate. No reference acquisition.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT), str(ROOT/'src'), str(ROOT/'tests')]
from verify import source_inventory


def main():
    import numpy as np
    import shapely
    from atlas_tectonics import (PreparedPrecursor, PrecursorExecutionPolicy,
        SphericalFrame, SphericalChart, GeometryLimits, PrecursorSamplingLimits,
        save_initial_samples, load_initial_samples)
    from atlas_tectonics.execution import ExecutionPolicy
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.storage import ArrayStore, StoreLimits
    from atlas_tectonics.precursor_sampling import _check_cell_overlaps, _check_cell_overlaps_reference
    from precursor_fixtures import state, mixed_case, cell, rectangle, REQUEST
    from test_precursor_scaling import patch
    before = source_inventory(ROOT)
    spec = json.loads((ROOT/'cases/precursor_r2_scaling.json').read_text())
    t = time.perf_counter(); s = state(mixed_case())
    points = np.tile([[2.,5.],[8.,5.]], (spec['measurements']['points']//2,1))
    depths = np.linspace(.1,29.9,len(points))
    point_setup = time.perf_counter()-t
    records = {}; samples = {}
    for mode in ('serial','auto'):
        b = WorkBudget(spec['measurements']['work_budget_bytes'])
        cfg = PrecursorExecutionPolicy(kernel=ExecutionPolicy(mode=mode,max_workers=2))
        t=time.perf_counter(); p=PreparedPrecursor(s,budget=b,execution_policy=cfg)
        setup = time.perf_counter()-t; elapsed=[]
        try:
            for _ in range(spec['measurements']['complete_call_repetitions']):
                t=time.perf_counter(); r=p.sample_points(points,depths,**REQUEST)
                elapsed.append(time.perf_counter()-t)
            records[mode]={'prepared_setup_s':setup,'first_complete_call_s':elapsed[0],
                'reused_complete_calls_s':elapsed[1:], 'execution':p.execution_statistics()}
            samples[mode]=r
        finally: p.close()
        if b.reserved_bytes: raise AssertionError('point resource leak')
        records[mode]['resources']=b.statistics()
    if samples['serial'].sample_id != samples['auto'].sample_id:
        raise AssertionError('parallel sample identity differs')
    for key in samples['serial']._buffers:
        np.testing.assert_array_equal(samples['serial'].array(key),samples['auto'].array(key))
    # A declared negative result: keep this comparison instead of dropping an
    # unfavourable case or forcing an automatic path that was measured slower.
    count=spec['measurements']['cells']
    t=time.perf_counter(); cs=tuple(cell(str(i),rectangle(i*10/count,(i+1)*10/count)) for i in range(count))
    cell_setup=time.perf_counter()-t; cell_records={}; cell_samples={}
    for mode in ('serial','threads'):
        b=WorkBudget(spec['measurements']['work_budget_bytes'])
        cfg=PrecursorExecutionPolicy(kernel=ExecutionPolicy(mode=mode,max_workers=2))
        t=time.perf_counter();p=PreparedPrecursor(s,budget=b,execution_policy=cfg)
        setup=time.perf_counter()-t;elapsed=[]
        try:
            for _ in range(spec['measurements']['complete_call_repetitions']):
                t=time.perf_counter();r=p.sample_cells(cs,**REQUEST);elapsed.append(time.perf_counter()-t)
            cell_records[mode]={'prepared_setup_s':setup,'first_complete_call_s':elapsed[0],
                'reused_complete_calls_s':elapsed[1:],'execution':p.execution_statistics()}
            cell_samples[mode]=r
        finally:p.close()
        if b.reserved_bytes:raise AssertionError('cell resource leak')
        cell_records[mode]['resources']=b.statistics()
    if cell_samples['serial'].sample_id!=cell_samples['threads'].sample_id:
        raise AssertionError('threaded cell identity differs')
    for key in cell_samples['serial']._buffers:
        np.testing.assert_array_equal(cell_samples['serial'].array(key),cell_samples['threads'].array(key))
    with PreparedPrecursor(s) as automatic:
        automatic.sample_cells(cs,**REQUEST)
        cell_default=automatic.execution_statistics()
        if cell_default['route']!='serial':raise AssertionError('default forced slower measured cell path')
    t=time.perf_counter();sf=SphericalFrame(1000.,'r2-scaling-synthetic-sphere');ch=SphericalChart(sf,(1.,0.,0.))
    n=spec['measurements']['spherical_footprints'];side=8
    spherical=tuple(cell(str(i),patch(ch,x=(i%side)*.05,y=(i//side)*.05,size=.005)) for i in range(n))
    spherical_setup=time.perf_counter()-t;overlap_records={}
    for name,fun in [('pairwise_reference',_check_cell_overlaps_reference),('indexed_default',_check_cell_overlaps)]:
        b=WorkBudget(spec['measurements']['work_budget_bytes']);elapsed=[];diags={}
        for _ in range(spec['measurements']['overlap_repetitions']):
            t=time.perf_counter()
            kw={'diagnostics':diags} if name=='indexed_default' else {}
            diags.clear();fun(spherical,GeometryLimits(),PrecursorSamplingLimits(),b,None,**kw)
            elapsed.append(time.perf_counter()-t)
        if b.reserved_bytes:raise AssertionError('overlap index leak')
        overlap_records[name]={'complete_validation_seconds':elapsed,
            'diagnostics':diags,'resources':b.statistics()}
    # Shared source-bound self-contained representation, no new storage path.
    b=WorkBudget(spec['measurements']['work_budget_bytes'])
    with tempfile.TemporaryDirectory() as td:
        with ArrayStore(Path(td)/'samples.db',StoreLimits(4096,16<<20,64<<20),budget=b) as store:
            r=cell_samples['threads'];t=time.perf_counter();save_initial_samples(r,store)
            save_s=time.perf_counter()-t;t=time.perf_counter();restored=load_initial_samples(store,r.sample_id)
            restore_s=time.perf_counter()-t
            for key in r._buffers:np.testing.assert_array_equal(r.array(key),restored.array(key))
            chunks=store.statistics()['unique_chunks'];save_initial_samples(cell_samples['serial'],store)
            if store.statistics()['unique_chunks']!=chunks:raise AssertionError('serial/thread duplicates stored twice')
            storage=store.statistics()
    if b.reserved_bytes:raise AssertionError('storage resource leak')
    after=source_inventory(ROOT)
    if after!=before:raise AssertionError('source changed during evidence run')
    print(json.dumps({'schema':'atlas.precursor-r2-scaling-evidence.v1',
        'status':'PASS_BOUNDED_R2_SCALING_CHECKS','scope':spec['scope'],
        'branch':'remake','github_base':spec['github_base'],'parent_delivery_sha256':spec['parent_delivery_sha256'],
        'source_sha256_before':before,'source_sha256_after':after,'source_unchanged':True,
        'runtime':{'python':platform.python_version(),'numpy':np.__version__,'shapely':shapely.__version__,
            'system':platform.system(),'machine':platform.machine(),'thread_environment':{k:os.environ.get(k) for k in
                ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS')}},
        'timing_notes':'Sequential cases share imported libraries and process caches; first/reused complete calls are separated; setup is not isolated cold-process startup; timing never gates correctness',
        'input_construction_seconds':{'state_and_points':point_setup,'cells':cell_setup,'spherical_cells':spherical_setup},
        'point_count':len(points),'points':records,'point_arrays_and_sample_ids_equal':True,
        'cell_count':len(cs),'cells':cell_records,'cell_arrays_and_sample_ids_equal':True,'default_cell_execution':cell_default,
        'spherical_cell_count':len(spherical),'spherical_overlap_validation':overlap_records,
        'both_validate_same_disjoint_inventory':True,
        'save_seconds':save_s,'restore_seconds':restore_s,'all_restored_arrays_exact':True,
        'storage':storage,'serial_thread_store_dedup_exact':True,
        'claims':{'timing_is_acceptance_gate':False,'universal_speedup':False,'RSS_cap':False,
                  'planetary_scale_acceptance':False,'Windows_tested':False,'physical_validation':False,
                  'new_tectonic_physics':False,'R3_started':False}},indent=2,allow_nan=False))
    return 0


if __name__=='__main__':raise SystemExit(main())
