#!/usr/bin/env python3
"""Same complete W03 steps: repeated setup versus automatically prepared sequence.

Includes context construction/closure in BOTH routes; excludes W01 initialisation.
No disk-cache hits, parallel workers, skipped loads or relaxed source checks.
"""
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import time

for key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMBA_NUM_THREADS'):
    os.environ.setdefault(key, '1')
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'tests')]
import numpy as np
from atlas_tectonics import advance_w03_columns, evolve_w03_columns
from test_w03_workflow import workflow_fixture, initialise, STEP


def main():
    cells, parcels, steps = 256, 128, 6
    source = workflow_fixture(cells=cells)
    state = initialise(source, subdivisions={'upper': 64, 'lower': 64})
    schedule = tuple(((i+1)*STEP, 1e6 if i % 2 == 0 else 0.) for i in range(steps))
    def separate():
        current = state
        for now, load in schedule:
            current = advance_w03_columns(current, time_s=now, top_effective_stress_pa=load)
        return current
    def prepared():
        return evolve_w03_columns(state, schedule)
    first = separate(); second = prepared()
    if first.state_id != second.state_id:
        raise ValueError('prepared and repeated W03 results differ')
    timings = {'separate_setup_per_step': [], 'prepared_sequence': []}
    for repeat in range(3):
        pair = [('separate_setup_per_step', separate), ('prepared_sequence', prepared)]
        if repeat % 2:
            pair.reverse()
        for label, run in pair:
            start = time.perf_counter(); result = run(); elapsed = time.perf_counter()-start
            if result.state_id != first.state_id:
                raise ValueError('timed W03 result differs')
            timings[label].append(elapsed)
    before = statistics.median(timings['separate_setup_per_step'])
    after = statistics.median(timings['prepared_sequence'])
    sources = (ROOT/'src/atlas_tectonics/w03_workflow.py', ROOT/'src/atlas_tectonics/reuse.py',
               ROOT/'tests/test_w03_workflow.py', Path(__file__))
    print(json.dumps(dict(status='PASS_BIT_IDENTICAL_STATE', platform=platform.platform(),
        python=sys.version.split()[0], numpy=np.__version__, columns=cells, parcels_per_column=parcels,
        sequential_steps=steps, parcel_updates=cells*parcels*steps, repetitions=3,
        timings_seconds=timings, median_separate_seconds=before, median_prepared_seconds=after,
        saved_seconds=before-after, saved_percent=100*(before-after)/before, speedup=before/after,
        final_state_id=first.state_id,
        scope='Complete stationary W03 sequence, including both-backend setup/closure in each route; shared W01 initialisation outside timing. All loads, physical calculations and existing source checks retained. No disk caching or workers. Not a whole-generator speedup.',
        source_sha256={p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}), indent=2))


if __name__ == '__main__':
    main()
