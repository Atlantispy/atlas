"""Temporary bounded W06 margin timing; imports excluded, preparation included."""
import os
for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'BLIS_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[key] = '1'

import json
import statistics
import time
import numpy as np
from atlas_tectonics.margin_cooling import PreparedMarginCooling
from test_w06_margin_cooling import inherited, PLATE

source = inherited()
times = (1e12, 2e14, 1e15)
edges = (0., 7000., 20000., 53000., 100000.)
args = dict(thinning_source_id='fixture', geometry_reference_id='reference-surface')


def sequence(reuse):
    started = time.perf_counter()
    outputs = []
    if reuse:
        with PreparedMarginCooling(source, 'continent', PLATE, **args) as plan:
            for moment in times:
                outputs.append(plan.evaluate(time_s=moment, epoch_id=source.case.epoch_id, depth_edges_m=edges))
    else:
        for moment in times:
            with PreparedMarginCooling(source, 'continent', PLATE, **args) as plan:
                outputs.append(plan.evaluate(time_s=moment, epoch_id=source.case.epoch_id, depth_edges_m=edges))
    return time.perf_counter()-started, outputs


fresh, prepared = [], []
for repeat in range(3):
    duration, baseline = sequence(False)
    fresh.append(duration)
    duration, candidate = sequence(True)
    prepared.append(duration)
    for a, b in zip(baseline, candidate):
        assert a.state_id == b.state_id
        np.testing.assert_array_equal(a.mean_temperature_k, b.mean_temperature_k)
        np.testing.assert_array_equal(a.outward_heat_j_m2, b.outward_heat_j_m2)

fresh_median, prepared_median = statistics.median(fresh), statistics.median(prepared)
try:
    from threadpoolctl import threadpool_info
    numerical_threads = [{key: p.get(key) for key in ('internal_api', 'num_threads', 'prefix')}
                         for p in threadpool_info()]
except ImportError:
    numerical_threads = 'threadpoolctl unavailable; process-local numerical thread environment explicitly one'
print(json.dumps(dict(fresh_seconds=fresh, prepared_seconds=prepared,
    fresh_median_s=fresh_median, prepared_median_s=prepared_median,
    saved_seconds=fresh_median-prepared_median,
    saved_percent=100*(fresh_median-prepared_median)/fresh_median,
    parity='identical state IDs, means and heat for all three outputs in all three repetitions',
    output_times_s=times, depth_edges_m=edges, numerical_threads=numerical_threads,
    includes='new ExecutionContext, source verification, coefficient preparation, all outputs, close',
    excludes='imports, initial W01 fixture creation and post-timing equality checks'), indent=2))
