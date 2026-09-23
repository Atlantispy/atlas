#!/usr/bin/env python3
"""Same complete W04 projections: fresh preparation versus shared preparation.

Both include context preparation and closure. W01/W03 inputs and surface inputs
are identical and prepared outside timing. No disk hits or skipped source checks.
"""
import argparse
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
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'),str(ROOT/'tests')]
import numpy as np
from atlas_tectonics import (FlexureParameters,W03ExecutionContext,advance_w03_columns,
    W04SupportPolicy,W04SurfaceInputs,PreparedW04Support,project_w04_support)
from test_w03_workflow import initialise,workflow_fixture,STEP


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output',type=Path)
    args = parser.parse_args()
    n,steps = 128,4
    start = time.perf_counter()
    ref = initialise(workflow_fixture(cells=n,length_m=100000.,width_m=1000.))
    ids = tuple(c['cell_id'] for c in ref.source_workflow.initial_samples.descriptor()['cells'])
    policy = W04SupportPolicy('synthetic-uniform-plate-benchmark','periodic-repetition','flexure',
        0.,1000.,.05,.01,FlexureParameters('synthetic','timing fixture, not calibration',7e10,1000.,.25,3300.,10.))
    reference_surface = W04SurfaceInputs(ref,ids,np.full(n,ref.reservoir_fluid_m3/n),np.zeros(n),source_id='reference-placement')
    schedule = []; current = ref
    with W03ExecutionContext() as context:
        for j in range(steps):
            current = advance_w03_columns(current,time_s=(j+1)*STEP,
                top_effective_stress_pa=1e6 if j%2==0 else 0.,context=context)
            pressure = (j+1)*100.*np.cos(2*np.pi*np.arange(n)/n)
            surface = W04SurfaceInputs(current,ids,np.full(n,current.reservoir_fluid_m3/n),
                pressure,source_id='prescribed-placement-and-additional-traction-'+str(j))
            schedule.append((current,surface))
    input_seconds = time.perf_counter()-start
    def separate():
        return tuple(project_w04_support(ref,s,reference_surface,u,policy) for s,u in schedule)
    def prepared():
        with PreparedW04Support(ref,reference_surface,policy) as plan:
            return tuple(plan.solve(s,u) for s,u in schedule)
    a,b = separate(),prepared()
    expected = tuple(x.result_id for x in a)
    if tuple(x.result_id for x in b) != expected:
        raise ValueError('prepared W04 changes outputs or provenance')
    timings = {'separate_preparation':[],'shared_preparation':[]}
    for repeat in range(3):
        pair = [('separate_preparation',separate),('shared_preparation',prepared)]
        if repeat%2:
            pair.reverse()
        for label,run in pair:
            start = time.perf_counter(); result = run(); elapsed = time.perf_counter()-start
            if tuple(x.result_id for x in result) != expected:
                raise ValueError('timed W04 result differs')
            timings[label].append(elapsed)
    before,after = (statistics.median(timings[k]) for k in ('separate_preparation','shared_preparation'))
    sources = [ROOT/'src/atlas_tectonics/w04_workflow.py',ROOT/'src/atlas_tectonics/w03_workflow.py',
        ROOT/'src/atlas_tectonics/column_loads.py',ROOT/'src/atlas_tectonics/reuse.py',
        ROOT/'tests/test_w03_workflow.py',Path(__file__)]
    record = dict(status='PASS_BIT_IDENTICAL_RESULTS_AND_PROVENANCE',columns=n,projections=steps,
        length_m=100000.,width_m=1000.,repetitions=3,platform=platform.platform(),
        python=sys.version.split()[0],numpy=np.__version__,input_preparation_seconds=input_seconds,
        timings_seconds=timings,median_separate_seconds=before,median_prepared_seconds=after,
        saved_seconds=before-after,saved_percent=100*(before-after)/before,speedup=before/after,
        result_ids=expected,scope='Complete W04 projection including source checks, input mapping, material/thermal/external load, FFT support and bounds. Both routes include setup/closure; same W01/W03 and surface input construction outside timing. No cache hits/workers/full terrain. Not an old-version or whole-generator speed claim.',
        source_sha256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    payload = json.dumps(record,indent=2); print(payload)
    if args.output:
        args.output.write_text(payload+'\n',encoding='utf-8')


if __name__ == '__main__':
    main()
