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

R = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1')  # resumability-r1 (pinned: copied from G/scripts)
TESTS = R.parents[2] / 'heat-repair-20261007' / 'source' / 'tectonics' / 'tests'
PRESSURE_FORCE = {'pressure_max_leaves': 2**19, 'initial_trace_max_leaves': 2**19}


def _digest(path):  # T/ps
    from hashlib import file_digest
    with Path(path).open('rb') as stream:
        return file_digest(stream, 'sha256').hexdigest()


def _seed(source, pin, target):  # T/ps: copied discipline of Steps 8-9's time_admission_parts.py
    if _digest(source) != pin or any(Path(str(source)+x).exists() for x in ('-wal', '-journal')):
        raise SystemExit('seed store changed or is not closed')
    with Path(source).open('rb') as reader, Path(target).open('xb') as writer:
        for block in iter(lambda: reader.read(1 << 20), b''):
            writer.write(block)
    if _digest(target) != pin or _digest(source) != pin:
        raise SystemExit('seeded store differs from its pin')


def _monitor_calls(spec):  # T/ps
    import importlib
    out = {}
    if not spec:
        return out
    mon = sys.monitoring
    tool = 3
    mon.use_tool_id(tool, 'ps-call-times')
    stacks, codes = {}, {}
    for item in spec.split(','):
        module, name = item.split(':')
        fn = getattr(importlib.import_module(module), name)
        code = fn.__code__
        codes[code] = name
        out[name] = []
        mon.set_local_events(tool, code, mon.events.PY_START | mon.events.PY_RETURN)
    def start(code, offset):
        if code in codes:
            frame = sys._getframe(1)
            info = {k: (len(v) if isinstance(v, (tuple, list)) else v) for k, v in frame.f_locals.items()
                    if k in ('compute_density', 'regions', 'max_leaves') and isinstance(v, (bool, int, tuple, list))}
            stacks.setdefault(code, []).append((time.perf_counter(), time.process_time(), info))
    def ret(code, offset, value):
        if code in codes and stacks.get(code):
            w0, c0, info = stacks[code].pop()
            out[codes[code]].append(dict(info, wall=round(time.perf_counter()-w0, 4), cpu=round(time.process_time()-c0, 4)))
    mon.register_callback(tool, mon.events.PY_START, start)
    mon.register_callback(tool, mon.events.PY_RETURN, ret)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output-dir', required=True)
    ap.add_argument('--runtime', default='rc1')
    ap.add_argument('--no-profile', action='store_true')
    ap.add_argument('--check-imports', action='store_true')  # T/ps: pre-flight, no admission
    ap.add_argument('--profile-admission', action='store_true')  # T/ps: cProfile admission too
    # T/ps: stop after admission + exterior inputs/identity (no pressure stage): the q02 cProfile arm
    # profiles admission only; the pressure split comes from the py-spy arm without in-process hooks.
    ap.add_argument('--admission-only', action='store_true')
    # T/ps: SMALL case = test_i04_actuated_force's coarse ceilings on the same fixture (shape only,
    # never a production figure): metrics max_leaves 64, witness refinements 8; pressure leaves 4096/64.
    ap.add_argument('--small', action='store_true')
    # T/ps: item 7's seeded store (Steps 8-9 S/time_admission_parts.py discipline): STORE@SHA256
    ap.add_argument('--seed-store', default=None)
    # T/ps: per-call wall times of named functions (module:function,...) via sys.monitoring local
    # PY_START/PY_RETURN on those code objects only; no runtime object is patched.
    ap.add_argument('--time-calls', default='')
    ap.add_argument('--pressure-leaves', type=int, nargs=2, default=None)  # T/ps: override (small only)
    args = ap.parse_args()
    if sys.flags.hash_randomization:
        raise SystemExit('set PYTHONHASHSEED=0')
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=False)
    epoch = {'start': time.time()}  # T/ps: wall-clock marks for the process-tree sampler
    seeded = None
    if args.seed_store:
        source, pin = args.seed_store.rsplit('@', 1)
        _seed(source, pin, out/'initial-measurements.sqlite')
        seeded = dict(source=str(Path(source).resolve()), sha256=pin, copied=True)
    rc1_env.install(args.runtime)
    frozen = args.runtime.startswith('frozen:')  # T/ps: src + helpers + heat-repair tests only
    if not frozen:
        sys.path.append(str(R / 'composed-r1' / 'ram'))
    sys.path.append(str(TESTS))
    if not frozen:
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
    if args.check_imports:  # T/ps
        import inspect
        print(json.dumps({k: getattr(v, '__file__', None) or inspect.getsourcefile(v) for k, v in vars(m).items()
                          if k in ('spatial', 'D', 'J', 'G', 'radial_differential_fixture', 'check_initial_pressure_force')}, indent=1))
        print('ACTUATED_CONTROL', m.ACTUATED_CONTROL, 'predictor', getattr(m.ACTUATED_CONTROL, 'interval_predictor_proposals', None))
        print('package_digest', rc1_env.package_digest())
        return
    parts = {}  # T/ps: name -> [cpu_s, wall_s]; wraps only this harness's namespace
    ids = {}  # T/ps: issued identities, as Steps 8-9's harness records them
    def with_ids(names, fn):
        def call(*a_, **k_):
            values = fn(*a_, **k_)
            for name, value in zip(names, values):
                for attr in ('bounds_id', 'geometry_id', 'partition_id'):
                    if hasattr(value, attr):
                        ids[name+'.'+attr] = str(getattr(value, attr))
            return values
        return call
    def timed(name, fn):
        def call(*a_, **k_):
            c0, w0 = time.process_time(), time.perf_counter()
            try:
                return fn(*a_, **k_)
            finally:
                parts[name] = [round(time.process_time()-c0, 2), round(time.perf_counter()-w0, 2)]
        return call
    class _TimedEnter:
        def __init__(self, name, cm):
            self._name, self._cm = name, cm
        def __enter__(self):
            return timed(self._name, self._cm.__enter__)()
        def __exit__(self, *exc):
            return self._cm.__exit__(*exc)
    real = m.spatial
    def no_policy(fn):  # T/ps --small: as test_i04_differential_pressure_path (no measure_policy)
        # (also no measurement-store reuse, which needs the policy's relative accuracy)
        drop = ('measure_policy', 'measurement_store', 'measurement_context')
        return lambda *a_, **k_: fn(*a_, **{k: v for k, v in k_.items() if k not in drop})
    if args.small:
        real = SimpleNamespace(initial_partition=real.initial_partition,
                               initial_metrics=no_policy(real.initial_metrics),
                               initial_spatial_owner=no_policy(real.initial_spatial_owner))
    m.spatial = SimpleNamespace(
        initial_partition=timed('initial_partition', with_ids(('current', 'partition'), real.initial_partition)),
        initial_metrics=timed('initial_metrics', with_ids(('bounds', 'mesh'), real.initial_metrics)),
        initial_spatial_owner=lambda *a_, **k_: _TimedEnter('initial_spatial_owner_enter',
                                                            real.initial_spatial_owner(*a_, **k_)))
    call_times = _monitor_calls(args.time_calls)
    require_strict_execution()
    budget = WorkBudget(16 << 30, max_predicate_work_units=1 << 44)
    phases, times = [], {}
    phase = lambda name: phases.append((name, round(time.perf_counter(), 2)))
    FRESH._seed_pinned()
    pressure_force = PRESSURE_FORCE
    if args.small:  # harness-only, in this process's module object; no file is changed
        FRESH.INITIAL_METRICS = dict(FRESH.INITIAL_METRICS, max_leaves=64, max_witness_refinements=8)
        FRESH.FIXTURE = {'pressure_space': 'q1-p0'}  # as test_i04_actuated_force (no material quadrature)
        pressure_force = {'pressure_max_leaves': 4096, 'initial_trace_max_leaves': 64}
        if args.pressure_leaves:
            pressure_force = {'pressure_max_leaves': args.pressure_leaves[0],
                              'initial_trace_max_leaves': args.pressure_leaves[1]}
    epoch['admission_start'] = time.time()  # T/ps
    admission_profiler = cProfile.Profile() if args.profile_admission else None  # T/ps
    t, w = time.process_time(), time.perf_counter()
    if admission_profiler:
        admission_profiler.enable()
    with threadpool_limits(1), FRESH.admission(m, budget=budget, artifacts=out, phase=phase) as a:
        if admission_profiler:
            admission_profiler.disable()
        times['admission'] = (time.process_time()-t, time.perf_counter()-w)
        if admission_profiler:
            admission_profiler.dump_stats(str(out/'admission.prof'))
        from atlas_tectonics.integration_regional_workflow import CollarWorkflow  # T/ps
        c0, w0 = time.process_time(), time.perf_counter()
        collar_, funding_ = a.case['collar'], a.case['funding']
        try:  # a failure here is recorded; the pressure measurement still runs
            workflow_id = CollarWorkflow._identity(collar_, funding_,
                CollarWorkflow._exterior_inputs(a.owner, collar_, funding_, budget))
        except Exception as error:  # noqa: BLE001
            workflow_id = 'FAILED: %s: %s' % (type(error).__name__, error)
        parts['exterior_inputs_and_identity'] = [round(time.process_time()-c0, 2), round(time.perf_counter()-w0, 2)]
        stopped = {}
        result = 'admission-only: pressure stage not run'  # T/ps

        def prepared(**kwargs):
            stopped.update({k: type(v).__name__ for k, v in kwargs.items()})
            return 'stopped-before-advance'
        if args.admission_only:  # T/ps
            epoch['admission_end'] = time.time()
        else:
            epoch['pressure_start'] = time.time()
            profiler = None if args.no_profile else cProfile.Profile()
            t, w = time.process_time(), time.perf_counter()
            if profiler:
                profiler.enable()
            result = m.check_initial_pressure_force(unittest.TestCase(), a.case, a.current, a.partition,
                a.owner.initial_state, force_control=m.ACTUATED_CONTROL, **pressure_force, prepared_control=prepared)
            if profiler:
                profiler.disable()
                profiler.dump_stats(str(out/'pressure-stage.prof'))
            times['pressure_force'] = (time.process_time()-t, time.perf_counter()-w)
            epoch['pressure_end'] = time.time()
    store_digest = _digest(out/'initial-measurements.sqlite')
    info = psutil.Process().memory_info()
    report = dict(times_cpu_wall_s={k: [round(a_, 2), round(b, 2)] for k, (a_, b) in times.items()},
                  profiled=not args.no_profile, result=result, prepared_control_received=stopped,
                  phases=phases, package_digest=rc1_env.package_digest(), runtime=args.runtime,
                  peak_working_set_mib=round(info.peak_wset/2**20), peak_commit_mib=round(info.peak_pagefile/2**20),
                  call_times=call_times,
                  small=args.small, pressure_force=pressure_force, identities=ids, seeded_store=seeded,
                  measurement_store_sha256=store_digest,
                  store_sidecars=[x for x in ('-wal', '-journal', '-shm')
                                  if Path(str(out/'initial-measurements.sqlite')+x).exists()],
                  store_unchanged_from_seed=None if seeded is None else store_digest == seeded['sha256'],
                  initial_metrics={k: str(v) for k, v in FRESH.INITIAL_METRICS.items()},
                  fixture=FRESH.FIXTURE,
                  budget=budget.statistics(), epoch=epoch, parts_cpu_wall_s=parts, workflow_id=workflow_id, profiled_admission=bool(admission_profiler),
                  module_files={k: getattr(sys.modules.get(n), '__file__', None) for k, n in (
                      ('FRESH', 'fresh_interval_driver'), ('spatial', 'private_heat_original_spatial_r1'),
                      ('D', 'probe_heat_original_connected_r9'), ('fixture', 'i04_differential_fixture'),
                      ('force', 'test_i04_differential_force'), ('G', 'atlas_tectonics.integration_differential_geometry'))})
    (out/'report.json').write_text(json.dumps(report, indent=1, default=str))
    print(json.dumps(report['times_cpu_wall_s']), report['peak_working_set_mib'], 'MiB peak')


if __name__ == '__main__':
    main()
