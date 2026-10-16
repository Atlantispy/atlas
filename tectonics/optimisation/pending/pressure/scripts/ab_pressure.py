"""A/B harness for the pressure-stage candidates (T/ps): stage-output identity and timings per arm.

Runs fresh_interval_driver's admission once (as profile_pressure_stage.py; --small uses the
actuated test's coarse ceilings), then the pressure/force stage once per arm, exactly as
advance_first_interval calls check_initial_pressure_force, with a prepared_control that
records the stage output and returns before the advance:
  forcing_id (the issued snapshot's result_id, a digest of its metadata and arrays), the sha256
  of the canonical descriptor, each array's sha256 and shape, integration_leaves, and the
  regional driver's driving_id.
Arms, comma-separated, run in order in this one process:
  serial          no parallel context (the default route)
  autoN           inside integration_pressure_walls.parallel(InterfaceParallelPolicy(mode='auto',
                  workers=N), the admission's strict reference ExecutionContext)
  autoN:I=MODE    the same with the proof-only test table {I: MODE}, MODE decline or crash;
                  a negative I counts from the last wall (the first arm's wall count)
Every arm's identity must equal the first arm's: prints ARMS EQUAL or ARMS DIFFER (exit 1).
A 0.5 s sampler records the working sets of this process and its children: TOTAL = parent +
workers at each sample, and each worker process's peak. Requires PYTHONHASHSEED=0. Writes
only inside --output-dir.
Usage: ab_pressure.py --output-dir SHORT_DIR --runtime frozen:<folder>|test:<folder> [--small]
       [--pressure-leaves A B] --arms serial[,auto2,...]
"""
import argparse
import json
import sys
import threading
import time
import unittest
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc1_env  # noqa: E402

R = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1')
TESTS = R.parents[2] / 'heat-repair-20261007' / 'source' / 'tectonics' / 'tests'
PRESSURE_FORCE = {'pressure_max_leaves': 2**19, 'initial_trace_max_leaves': 2**19}


def _arms(text):
    arms = []
    for item in text.split(','):
        name, *tests = item.split(':')
        if name == 'serial':
            workers = None
        elif name.startswith('auto') and name[4:].isdigit():
            workers = int(name[4:])
        else:
            raise SystemExit('unknown arm '+item)
        table = {}
        for test in tests:
            index, _, mode = test.partition('=')
            if mode not in ('decline', 'crash') or workers is None:
                raise SystemExit('test entries are I=decline|crash on an auto arm: '+item)
            table[int(index)] = mode
        arms.append(dict(arm=item, workers=workers, test=table))
    return arms


class _Sampler(threading.Thread):
    """Working sets of this process and its children every 0.5 s (TOTAL and per-worker peaks)."""

    def __init__(self, psutil):
        super().__init__(daemon=True)
        self.psutil, self.me, self.stop_event = psutil, psutil.Process(), threading.Event()
        self.total_peak, self.parent_peak, self.children = 0, 0, {}

    def run(self):
        while not self.stop_event.wait(0.5):
            try:
                parent = self.me.memory_info().rss
                total = parent
                for child in self.me.children(recursive=True):
                    try:
                        info = child.memory_info()
                        row = self.children.setdefault(child.pid, dict(
                            worker=any('integration_parallel_worker' in part for part in child.cmdline()),
                            peak_wset=0, rss=0))
                        row['peak_wset'] = max(row['peak_wset'], getattr(info, 'peak_wset', info.rss))
                        row['rss'] = max(row['rss'], info.rss)
                        total += info.rss
                    except self.psutil.Error:
                        pass
                self.parent_peak = max(self.parent_peak, parent)
                self.total_peak = max(self.total_peak, total)
            except self.psutil.Error:
                pass

    def result(self):
        self.stop_event.set()
        self.join(5)
        workers = [row for row in self.children.values() if row['worker']]
        mib = lambda b: round(b/2**20)
        return dict(total_peak_mib=mib(self.total_peak), parent_peak_rss_mib=mib(self.parent_peak),
                    worker_processes=len(workers),
                    worker_peak_wset_mib=sorted((mib(row['peak_wset']) for row in workers), reverse=True)[:16],
                    other_children=len(self.children)-len(workers))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output-dir', required=True)
    ap.add_argument('--runtime', required=True)
    ap.add_argument('--arms', required=True)
    ap.add_argument('--small', action='store_true')
    ap.add_argument('--pressure-leaves', type=int, nargs=2, default=None)
    args = ap.parse_args()
    if sys.flags.hash_randomization:
        raise SystemExit('set PYTHONHASHSEED=0')
    arms = _arms(args.arms)
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=False)
    rc1_env.install(args.runtime)
    frozen = args.runtime.startswith('frozen:')  # as profile_pressure_stage.py: frozen = src + helpers + tests
    if not frozen:
        sys.path.append(str(R / 'composed-r1' / 'ram'))
    sys.path.append(str(TESTS))
    if not frozen:
        sys.path.append(str(R))
    from types import SimpleNamespace
    import importlib
    import psutil
    from atlas_tectonics import integration_differential_geometry as G
    from atlas_tectonics import integration_parallel_selection as S
    from atlas_tectonics.reuse import ExecutionContext, require_strict_execution
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.storage import ArrayStore, Compression, StoreLimits
    from threadpoolctl import threadpool_limits
    import fresh_interval_driver as FRESH
    try:
        from atlas_tectonics import integration_pressure_walls as W
    except ImportError:
        W = None
    if W is None and any(arm['workers'] is not None for arm in arms):
        raise SystemExit('this runtime has no integration_pressure_walls: serial arms only')
    module = importlib.import_module
    m = SimpleNamespace(
        ExecutionContext=ExecutionContext, ArrayStore=ArrayStore, StoreLimits=StoreLimits, Compression=Compression,
        radial_differential_fixture=module('i04_differential_fixture').radial_differential_fixture,
        spatial=module('private_heat_original_spatial_r1'), D=module('probe_heat_original_connected_r9'),
        J=module('private_heat_joined_consumer_r6'), G=G,
        check_initial_pressure_force=module('test_i04_differential_force').check_initial_pressure_force,
        ACTUATED_CONTROL=module('i04_differential_modes').ACTUATED_CONTROL)
    if args.small:
        real = m.spatial
        drop = ('measure_policy', 'measurement_store', 'measurement_context')
        no_policy = lambda fn: lambda *a_, **k_: fn(*a_, **{k: v for k, v in k_.items() if k not in drop})
        m.spatial = SimpleNamespace(initial_partition=real.initial_partition,
                                    initial_metrics=no_policy(real.initial_metrics),
                                    initial_spatial_owner=no_policy(real.initial_spatial_owner))
    require_strict_execution()
    budget = WorkBudget(16 << 30, max_predicate_work_units=1 << 44)
    FRESH._seed_pinned()
    pressure_force = PRESSURE_FORCE
    if args.small:  # harness-only, in this process's module object; no file is changed
        FRESH.INITIAL_METRICS = dict(FRESH.INITIAL_METRICS, max_leaves=64, max_witness_refinements=8)
        FRESH.FIXTURE = {'pressure_space': 'q1-p0'}
        pressure_force = {'pressure_max_leaves': 4096, 'initial_trace_max_leaves': 64}
    if args.pressure_leaves:
        pressure_force = {'pressure_max_leaves': args.pressure_leaves[0],
                          'initial_trace_max_leaves': args.pressure_leaves[1]}
    physical = psutil.cpu_count(logical=False) or 1
    report = dict(runtime=args.runtime, package_digest=rc1_env.package_digest(), small=args.small,
                  pressure_force=pressure_force, physical_cores=physical, arms=[],
                  module_files={k: getattr(sys.modules.get(n), '__file__', None) for k, n in (
                      ('FRESH', 'fresh_interval_driver'), ('force', 'test_i04_differential_force'),
                      ('walls', 'atlas_tectonics.integration_pressure_walls'),
                      ('pressure', 'atlas_tectonics.integration_differential_pressure'))})
    t, w = time.process_time(), time.perf_counter()
    with threadpool_limits(1), FRESH.admission(m, budget=budget, artifacts=out, phase=lambda name: None) as a:
        report['admission_cpu_wall_s'] = [round(time.process_time()-t, 2), round(time.perf_counter()-w, 2)]
        # Upstream identities the stage inherits (D-b classification: a forcing_id that differs only
        # because these differ is an execution-identity change, not a number change).
        def ident(obj, *names):
            for name in names:
                obj = getattr(obj, name, None) if not isinstance(obj, dict) else obj.get(name)
            return None if obj is None else str(obj)
        report['admission_ids'] = dict(
            geometry_id=ident(a.current, 'geometry_id'), spatial_owner_id=ident(a.owner, 'owner_id'),
            spatial_state_id=ident(a.owner, 'initial_state', 'state_id'),
            native_state_id=ident(a.case, 'state', 'native_state', 'result_id'),
            funding_id=ident(a.case, 'funding', 'funding_id'), collar_plan_id=ident(a.case, 'collar', 'plan_id'),
            native_plan_id=ident(a.case, 'native', 'plan_id'), owner_id=ident(a.case, 'owner', 'owner_id'),
            reference_execution=ident(a.reference_execution, 'identity'))
        walls = None
        for arm in arms:
            identity = {}

            def prepared(*, driver, pressure, datum, **extra):
                snapshot = pressure._snapshot
                descriptor = pressure.descriptor()
                (out/('descriptor-%d.json' % len(report['arms']))).write_text(
                    json.dumps(descriptor, sort_keys=True, indent=0, default=repr), encoding='utf8')
                identity.update(
                    forcing_id=pressure.forcing_id,
                    descriptor_sha256=sha256(json.dumps(descriptor, sort_keys=True, separators=(',', ':'),
                                                        default=repr).encode()).hexdigest(),
                    arrays={key: dict(sha256=sha256(raw).hexdigest(), shape=list(shape))
                            for key, shape, raw in snapshot._fields},
                    integration_leaves=descriptor.get('integration_leaves'),
                    driving_id=str(driver.driving_id), datum=repr(datum.record()), extra=sorted(extra))
                return 'stopped-before-advance'
            table = {}
            for index, mode in arm['test'].items():
                if index < 0:
                    if walls is None:
                        raise SystemExit('a negative test index needs an earlier arm with the wall count')
                    index += walls
                table[index] = mode
            free = physical*(1-psutil.cpu_percent(interval=1)/100)
            sampler = _Sampler(psutil)
            sampler.start()
            t, w = time.process_time(), time.perf_counter()
            try:
                if arm['workers'] is None:
                    m.check_initial_pressure_force(unittest.TestCase(), a.case, a.current, a.partition,
                        a.owner.initial_state, force_control=m.ACTUATED_CONTROL, **pressure_force,
                        prepared_control=prepared)
                else:
                    policy = S.InterfaceParallelPolicy(mode='auto', workers=arm['workers'])
                    with W.parallel(policy, a.reference_execution, test=table):
                        m.check_initial_pressure_force(unittest.TestCase(), a.case, a.current, a.partition,
                            a.owner.initial_state, force_control=m.ACTUATED_CONTROL, **pressure_force,
                            prepared_control=prepared)
            finally:
                seconds = [round(time.process_time()-t, 2), round(time.perf_counter()-w, 2)]
                memory = sampler.result()
            walls_report = W.reports()[-1] if W is not None and W.reports() else None
            if walls_report is not None and walls is None:
                walls = walls_report['walls']
            row = dict(arm=arm['arm'], test=table, free_cores_at_start=round(free, 2), parent_cpu_wall_s=seconds,
                       memory=memory, identity=identity, walls=walls_report)
            report['arms'].append(row)
            (out/'report.json').write_text(json.dumps(report, indent=1, default=str))
            print(json.dumps(dict(arm=row['arm'], cpu_wall_s=seconds, forcing_id=identity.get('forcing_id'),
                                  route=(walls_report or {}).get('route'), reason=(walls_report or {}).get('reason'),
                                  workers=(walls_report or {}).get('workers'),
                                  adopted=(walls_report or {}).get('adopted'),
                                  recomputed=(walls_report or {}).get('recomputed'),
                                  total_peak_mib=memory['total_peak_mib'])), flush=True)
    keys = ('forcing_id', 'descriptor_sha256', 'arrays', 'integration_leaves', 'driving_id', 'datum')
    first = {k: report['arms'][0]['identity'].get(k) for k in keys}
    equal = all({k: row['identity'].get(k) for k in keys} == first for row in report['arms'])
    report['arms_equal'] = equal
    report['budget'] = budget.statistics()
    (out/'report.json').write_text(json.dumps(report, indent=1, default=str))
    print('ARMS EQUAL' if equal else 'ARMS DIFFER', first['forcing_id'], first['integration_leaves'])
    raise SystemExit(0 if equal else 1)


if __name__ == '__main__':
    main()
