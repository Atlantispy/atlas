#!/usr/bin/env python3
"""Same guarded constitutive law: separate column calls versus one bounded batch."""
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
sys.path.insert(0, str(ROOT/'src'))
import numpy as np
from atlas_tectonics import CompactionParameters, compaction_response


def main():
    p = CompactionParameters('benchmark', 'synthetic law, not sediment calibration', .1, .02, 1e5, 1e8, 0., .8)
    parcels, columns = 64, 1024
    e = np.full((parcels, columns), .8)
    old = np.broadcast_to(np.linspace(1e4, 2e6, parcels)[:, None], e.shape).copy()
    peak = old*1.2
    new = old*np.linspace(.5, 2., columns)[None, :]
    def separate_columns():
        out = np.empty(e.shape+(2,))
        for c in range(columns):
            out[:, c] = compaction_response(e[:, c], old[:, c], peak[:, c], new[:, c], p)
        return out
    def batch():
        return compaction_response(e, old, peak, new, p)
    expected = separate_columns(); actual = batch()
    if not np.array_equal(expected, actual):
        raise ValueError('batched and per-column constitutive results differ')
    timings = {'separate_column_calls': [], 'bounded_batch': []}
    for i in range(3):
        pair = [('separate_column_calls', separate_columns), ('bounded_batch', batch)]
        if i % 2: pair.reverse()
        for label, run in pair:
            start = time.perf_counter(); run(); timings[label].append(time.perf_counter()-start)
    before = statistics.median(timings['separate_column_calls'])
    after = statistics.median(timings['bounded_batch'])
    sources = (ROOT/'src/atlas_tectonics/compaction.py', ROOT/'src/atlas_tectonics/compaction_columns.py',
               ROOT/'src/atlas_tectonics/reuse.py', Path(__file__))
    print(json.dumps(dict(status='PASS_BIT_IDENTICAL', platform=platform.platform(), python=sys.version.split()[0],
        numpy=np.__version__, parcels_per_column=parcels, columns=columns, parcel_updates=parcels*columns,
        repetitions=3, timings_seconds=timings, median_reference_seconds=before, median_batch_seconds=after,
        saved_seconds=before-after, saved_percent=100*(before-after)/before, speedup=before/after,
        scope='Same guarded law, vectorised within each baseline column. Measures batching independent columns, not an older production stage or external software. No disk cache, JIT or worker pool in timed routes.',
        source_sha256={path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}), indent=2))


if __name__ == '__main__':
    main()
