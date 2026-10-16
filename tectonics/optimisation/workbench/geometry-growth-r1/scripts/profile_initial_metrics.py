"""Read-only profile of route (1)'s fresh admission: fixture, initial partition, initial metrics.

Repeats fresh_interval_driver._admission up to and including
m.spatial.initial_metrics with r9's literals (FIXTURE, MEASUREMENT_CACHE, INITIAL_PARTITION,
INITIAL_METRICS), a NEW measurement store in a scratch folder (as every route (1) process
has), the RC1 runtime and the composition's helper modules. cProfile covers initial_metrics
only; the fixture and partition are timed apart. Nothing is published or written outside
the output folder. Requires PYTHONHASHSEED=0.
Usage: profile_initial_metrics.py --output-dir DIR [--no-profile]
"""
import argparse
import cProfile
import json
import sys
import time
from fractions import Fraction as Q
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc1_env  # noqa: E402

D_ROOT = HERE.parents[4]            # .../fidelity-integration-20261005
TESTS = D_ROOT / 'heat-repair-20261007' / 'source' / 'tectonics' / 'tests'
FIXTURE = {'pressure_space': 'q1-p0', 'material_quadrature': True}
MEASUREMENT_CACHE = {'chunk_bytes': 65536, 'max_array_bytes': 1 << 20, 'max_store_bytes': 128 << 20}
INITIAL_PARTITION = {'max_components': 4096}
INITIAL_METRICS = {'physical_volume_error_m3': Q(32000), 'thermal_volume_error_m3': Q(32000),
                   'max_leaves': 2**30, 'max_witness_refinements': 32}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output-dir', required=True)
    ap.add_argument('--no-profile', action='store_true')
    ap.add_argument('--runtime', default='rc1', help='rc1 or test:<composition folder>')
    args = ap.parse_args()
    if sys.flags.hash_randomization:
        raise SystemExit('set PYTHONHASHSEED=0')
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=False)
    rc1_env.install(args.runtime)
    # The route (1) runner's import roots (composed-r1/manifest.json layout): helpers (added by
    # rc1_env), ram, and the heat-repair test fixtures.
    sys.path.append(str(HERE.parents[1] / 'composed-r1' / 'ram'))
    sys.path.append(str(TESTS))
    import psutil
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.reuse import ExecutionContext, require_strict_execution
    from atlas_tectonics.storage import ArrayStore, Compression, StoreLimits
    import i04_differential_fixture as F
    import private_heat_original_spatial_r1 as spatial
    import probe_heat_original_connected_r9 as D
    require_strict_execution()
    budget = WorkBudget(16 << 30, max_predicate_work_units=1 << 44)
    times = {}
    t = time.process_time(); w = time.perf_counter()
    with ExecutionContext('reference') as reference, ExecutionContext('scipy'), \
            ArrayStore(out/'initial-measurements.sqlite', StoreLimits(**MEASUREMENT_CACHE),
                       Compression(codec='raw'), budget=budget) as cache, \
            F.radial_differential_fixture(budget=budget, **FIXTURE) as case:
        times['fixture'] = (time.process_time()-t, time.perf_counter()-w)
        t = time.process_time(); w = time.perf_counter()
        current, partition = spatial.initial_partition(case, **INITIAL_PARTITION)
        times['initial_partition'] = (time.process_time()-t, time.perf_counter()-w)
        profiler = None if args.no_profile else cProfile.Profile()
        t = time.process_time(); w = time.perf_counter()
        if profiler:
            profiler.enable()
        bounds, mesh = spatial.initial_metrics(case, partition, **INITIAL_METRICS, measure_policy=D.POLICY,
                                               measurement_store=cache, measurement_context=reference)
        if profiler:
            profiler.disable()
            profiler.dump_stats(str(out/'initial-metrics.prof'))
        times['initial_metrics'] = (time.process_time()-t, time.perf_counter()-w)
        identity = dict(bounds_type=type(bounds).__name__, mesh_type=type(mesh).__name__)
        for name, value in (('bounds', bounds), ('mesh', mesh)):
            for attr in ('bounds_id', 'mesh_id', 'metric_id', 'id'):
                if hasattr(value, attr):
                    identity[name+'.'+attr] = str(getattr(value, attr))
            # Full issued record, for a field-by-field comparison across runtimes.
            if callable(getattr(value, 'record', None)):
                import gzip as _gzip
                body = json.dumps(value.record(), sort_keys=True, default=str).encode()
                (out/(name+'-record.json.gz')).write_bytes(_gzip.compress(body))
    info = psutil.Process().memory_info()
    report = dict(times_cpu_wall_s={k: [round(a, 2), round(b, 2)] for k, (a, b) in times.items()},
                  profiled=not args.no_profile, identity=identity, package_digest=rc1_env.package_digest(),
                  peak_working_set_mib=round(info.peak_wset/2**20), peak_commit_mib=round(info.peak_pagefile/2**20),
                  measurement_store_bytes=(out/'initial-measurements.sqlite').stat().st_size,
                  budget=budget.statistics())
    (out/'report.json').write_text(json.dumps(report, indent=1, default=str))
    print(json.dumps(report['times_cpu_wall_s']), report['peak_working_set_mib'], 'MiB peak')


if __name__ == '__main__':
    main()
