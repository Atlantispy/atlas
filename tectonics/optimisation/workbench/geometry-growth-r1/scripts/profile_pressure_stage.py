"""Read-only profile of route (1)'s initial pressure/force stage, stopped before the advance.

Builds the same module namespace as run_fresh_interval.composition (r9's modules), runs
fresh_interval_driver's admission unchanged, then calls check_initial_pressure_force exactly as
advance_first_interval does (ACTUATED_CONTROL, pressure_max_leaves = initial_trace_max_leaves =
2**19) with a prepared_control that returns at once, so nothing opens a store or advances.
cProfile covers the pressure/force call only; admission is timed apart. The measurement cache
is a NEW store in the output folder. Requires PYTHONHASHSEED=0.
Usage: profile_pressure_stage.py --output-dir SHORT_DIR [--runtime rc1|test:<folder>] [--no-profile]
"""
import argparse
import cProfile
import json
import sys
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc1_env  # noqa: E402

R = HERE.parents[1]                 # resumability-r1
TESTS = HERE.parents[4] / 'heat-repair-20261007' / 'source' / 'tectonics' / 'tests'
PRESSURE_FORCE = {'pressure_max_leaves': 2**19, 'initial_trace_max_leaves': 2**19}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output-dir', required=True)
    ap.add_argument('--runtime', default='rc1')
    ap.add_argument('--no-profile', action='store_true')
    args = ap.parse_args()
    if sys.flags.hash_randomization:
        raise SystemExit('set PYTHONHASHSEED=0')
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=False)
    rc1_env.install(args.runtime)
    sys.path.append(str(R / 'composed-r1' / 'ram'))
    sys.path.append(str(TESTS))
    sys.path.append(str(R))
    from types import SimpleNamespace
    import importlib
    import psutil
    from atlas_tectonics import integration_differential_geometry as G
    from atlas_tectonics.reuse import ExecutionContext, require_strict_execution
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.storage import ArrayStore, Compression, StoreLimits
    from threadpoolctl import threadpool_limits
    import fresh_interval_driver as FRESH
    module = importlib.import_module
    m = SimpleNamespace(
        ExecutionContext=ExecutionContext, ArrayStore=ArrayStore, StoreLimits=StoreLimits, Compression=Compression,
        radial_differential_fixture=module('i04_differential_fixture').radial_differential_fixture,
        spatial=module('private_heat_original_spatial_r1'), D=module('probe_heat_original_connected_r9'),
        J=module('private_heat_joined_consumer_r6'), G=G,
        check_initial_pressure_force=module('test_i04_differential_force').check_initial_pressure_force,
        ACTUATED_CONTROL=module('i04_differential_modes').ACTUATED_CONTROL)
    require_strict_execution()
    budget = WorkBudget(16 << 30, max_predicate_work_units=1 << 44)
    phases, times = [], {}
    phase = lambda name: phases.append((name, round(time.perf_counter(), 2)))
    FRESH._seed_pinned()
    t, w = time.process_time(), time.perf_counter()
    with threadpool_limits(1), FRESH.admission(m, budget=budget, artifacts=out, phase=phase) as a:
        times['admission'] = (time.process_time()-t, time.perf_counter()-w)
        stopped = {}

        def prepared(**kwargs):
            stopped.update({k: type(v).__name__ for k, v in kwargs.items()})
            return 'stopped-before-advance'
        profiler = None if args.no_profile else cProfile.Profile()
        t, w = time.process_time(), time.perf_counter()
        if profiler:
            profiler.enable()
        result = m.check_initial_pressure_force(unittest.TestCase(), a.case, a.current, a.partition,
            a.owner.initial_state, force_control=m.ACTUATED_CONTROL, **PRESSURE_FORCE, prepared_control=prepared)
        if profiler:
            profiler.disable()
            profiler.dump_stats(str(out/'pressure-stage.prof'))
        times['pressure_force'] = (time.process_time()-t, time.perf_counter()-w)
    info = psutil.Process().memory_info()
    report = dict(times_cpu_wall_s={k: [round(a_, 2), round(b, 2)] for k, (a_, b) in times.items()},
                  profiled=not args.no_profile, result=result, prepared_control_received=stopped,
                  phases=phases, package_digest=rc1_env.package_digest(), runtime=args.runtime,
                  peak_working_set_mib=round(info.peak_wset/2**20), peak_commit_mib=round(info.peak_pagefile/2**20),
                  budget=budget.statistics())
    (out/'report.json').write_text(json.dumps(report, indent=1, default=str))
    print(json.dumps(report['times_cpu_wall_s']), report['peak_working_set_mib'], 'MiB peak')


if __name__ == '__main__':
    main()
