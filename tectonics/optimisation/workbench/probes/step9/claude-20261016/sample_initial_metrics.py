"""Read-only: a statistical stack profile of route (1)'s initial_metrics, without cProfile's inflation.

Usage: python -B sample_initial_metrics.py OUTDIR NATIVE_ROOT IMPORT_ROOT [IMPORT_ROOT ...]

The same calls as time_admission_parts.py --metrics-only (the driver's literals; a NEW
measurement store in OUTDIR). While initial_metrics runs, a daemon thread wakes every
INTERVAL seconds and records the main thread's Python stack (sys._current_frames): the top
frame (exclusive) and every distinct function and module file on the stack (inclusive). Cost:
one stack walk per wake-up, about 1-2% here. C code that holds the GIL is attributed to the
Python frame that called it. Writes OUTDIR/samples.json only. Requires PYTHONHASHSEED=0.
"""
import json
import sys
import threading
import time
from collections import Counter
from fractions import Fraction as Q
from pathlib import Path

FIXTURE = {'pressure_space': 'q1-p0', 'material_quadrature': True}
MEASUREMENT_CACHE = {'chunk_bytes': 65536, 'max_array_bytes': 1 << 20, 'max_store_bytes': 128 << 20}
MEASUREMENT_CODEC = 'raw'
INITIAL_PARTITION = {'max_components': 4096}
INITIAL_METRICS = {'physical_volume_error_m3': Q(32000), 'thermal_volume_error_m3': Q(32000),
                   'max_leaves': 2**30, 'max_witness_refinements': 32}
INTERVAL = .01
TOP = 60


class Sampler(threading.Thread):
    def __init__(self, target_id):
        super().__init__(daemon=True)
        self.target_id, self.stop_event = target_id, threading.Event()
        self.samples, self.exclusive, self.inclusive, self.files = 0, Counter(), Counter(), Counter()

    def run(self):
        while not self.stop_event.wait(INTERVAL):
            frame = sys._current_frames().get(self.target_id)
            if frame is None:
                continue
            self.samples += 1
            seen, files = set(), set()
            top = True
            while frame is not None:
                code = frame.f_code
                name = Path(code.co_filename).name
                key = f'{name}:{code.co_name}:{code.co_firstlineno}'
                if top:
                    self.exclusive[key] += 1
                    top = False
                if key not in seen:
                    seen.add(key)
                    self.inclusive[key] += 1
                files.add(name)
                frame = frame.f_back
            for name in files:
                self.files[name] += 1

    def report(self):
        def share(counter):
            return [[key, count, round(count/max(1, self.samples), 4)] for key, count in counter.most_common(TOP)]
        return dict(samples=self.samples, interval_s=INTERVAL, exclusive=share(self.exclusive),
                    inclusive=share(self.inclusive), files=share(self.files))


def main():
    if sys.flags.hash_randomization:
        raise SystemExit('set PYTHONHASHSEED=0')
    out, native, roots = Path(sys.argv[1]), Path(sys.argv[2]).resolve(), [Path(p).resolve() for p in sys.argv[3:]]
    out.mkdir(parents=True, exist_ok=False)
    sys.path[:0] = [str(native), *map(str, roots)]
    import atlas_tectonics
    if not Path(str(atlas_tectonics.__file__)).resolve().is_relative_to(native):
        raise SystemExit('atlas_tectonics did not load from the native root')
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.reuse import ExecutionContext, require_strict_execution
    from atlas_tectonics.storage import ArrayStore, Compression, StoreLimits
    import i04_differential_fixture as F
    import private_heat_original_spatial_r1 as spatial
    import probe_heat_original_connected_r9 as D
    require_strict_execution()
    budget = WorkBudget(16 << 30, max_predicate_work_units=1 << 44)
    with ExecutionContext('reference') as reference, ExecutionContext('scipy'), \
            ArrayStore(out/'initial-measurements.sqlite', StoreLimits(**MEASUREMENT_CACHE),
                       Compression(codec=MEASUREMENT_CODEC), budget=budget) as cache, \
            F.radial_differential_fixture(budget=budget, **FIXTURE) as case:
        current, partition = spatial.initial_partition(case, **INITIAL_PARTITION)
        sampler = Sampler(threading.get_ident())
        cpu, wall = time.process_time(), time.perf_counter()
        sampler.start()
        try:
            bounds, mesh = spatial.initial_metrics(case, partition, **INITIAL_METRICS, measure_policy=D.POLICY,
                                                   measurement_store=cache, measurement_context=reference)
        finally:
            sampler.stop_event.set()
            sampler.join()
        cpu, wall = time.process_time()-cpu, time.perf_counter()-wall
        del bounds, mesh, current, partition
    report = dict(native_root=str(native), import_roots=list(map(str, roots)),
                  initial_metrics_cpu_s=round(cpu, 2), initial_metrics_wall_s=round(wall, 2), **sampler.report())
    (out/'samples.json').write_text(json.dumps(report, indent=1), encoding='utf8')
    print(json.dumps({'cpu_s': report['initial_metrics_cpu_s'], 'samples': report['samples']}))


if __name__ == '__main__':
    main()
