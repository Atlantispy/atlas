"""Geometry-transfer binding: booked and real memory and time, before and after.

Usage: python -B measure_geometry_transfer.py MODE OUT.json
MODE 'before' loads the pre-edit copy in before-src as geometry_transfer;
'after' uses R/geometry_transfer.py. Run each mode in its own process. Both
bind the tiny actual fixture of test_geometry_transfer_compact (native
transfer, collar, funding, evolved interval, compact parent) through the
compact and the dict routes and record:
  booked: peak of the binding's own concurrent geometry-transfer-*
          reservations (each reserve/exit on the shared budget tracked by a
          test-only wrapper around WorkBudget.reserve in this process);
  time:   median wall seconds per bind (no tracemalloc in this pass);
  real:   tracemalloc peak during each bind, in a separate later pass;
  record: SHA-256 of the binding record bytes (must equal across modes).
The authentic restart parent is produced by Step 9's migration, so this is the
tiny fixture; the scratch formula terms are reported so an IV1 figure can be
computed from real record sizes.
"""
import gc
import hashlib
import importlib.util
import json
import os
import statistics
import sys
import time
import tracemalloc

HERE = os.path.dirname(os.path.abspath(__file__))
R = os.path.normpath(os.path.join(HERE, '..', '..', '..'))
C = os.path.join(R, 'compact-geometry-r1')
I = os.path.join(os.path.dirname(R), 'runtime-integration-r1', 'runtime-src')
REVIEWED = os.path.join(R, 'composed-r1', 'runtime-src', 'atlas_tectonics', 'integration_endpoint_checkpoints.py')
REPEATS = 7


def main():
    mode, out = sys.argv[1], sys.argv[2]
    if mode not in ('before', 'after'):
        raise SystemExit('MODE must be before or after')
    os.chdir(C)
    sys.path.insert(0, C)
    sys.path.extend([I, R])
    if mode == 'before':
        path = os.path.join(HERE, 'before-src', 'geometry_transfer.py')
        spec = importlib.util.spec_from_file_location('geometry_transfer', path)
        module = importlib.util.module_from_spec(spec)
        sys.modules['geometry_transfer'] = module
        spec.loader.exec_module(module)
    import test_geometry_transfer_compact as TGC
    G = TGC.G
    # As run_partition_with_query_store.py MODE reviewed: WP10's in-progress
    # endpoint companion imports a module the staged seam does not emit, so
    # the temporary package gets the reviewed companion (hash-checked) instead.
    compose = TGC.compose

    def reviewed_compose(package, PN):
        stages = compose(package, PN)
        raw = open(REVIEWED, 'rb').read()
        if not hashlib.sha256(raw).hexdigest().startswith('4a835dc3'):
            raise RuntimeError('reviewed companion copy changed')
        (package/'integration_endpoint_checkpoints.py').write_bytes(raw)
        return stages

    TGC.compose = reviewed_compose
    # The fixture composes and imports its own runtime package (clean process
    # only), so its WorkBudget class exists after setUpModule.
    TGC.setUpModule()
    budget_class = TGC.WorkBudget
    state = {'now': 0, 'peak': 0}
    original = budget_class.reserve

    class Tracked:
        def __init__(self, guard, size):
            self.guard, self.size = guard, size

        def __enter__(self):
            value = self.guard.__enter__()
            state['now'] += self.size
            state['peak'] = max(state['peak'], state['now'])
            return value

        def __exit__(self, *exc):
            state['now'] -= self.size
            return self.guard.__exit__(*exc)

    def reserve(self, size, *args, **kwargs):
        guard = original(self, size, *args, **kwargs)
        if str(kwargs.get('category', '')).startswith('geometry-transfer-'):
            return Tracked(guard, size)
        return guard

    budget_class.reserve = reserve
    cls = TGC.CompactGeometryTransferTests
    cls.setUpClass()
    case = cls('test_lifetime_and_zero_final_reservations')
    case.setUp()
    report = {'mode': mode, 'module_file': G.__file__,
              'module_sha256': hashlib.sha256(open(G.__file__, 'rb').read()).hexdigest(), 'routes': {}}
    try:
        view = TGC.compact(case.body, case.supports, case.budget)
        native = case.fixture.native_owned
        report['formula_terms'] = {
            'transfer_record_bytes': len(native._record),
            'transfer_record_decode_bytes': G._json_decode_bytes(native._record),
            'plan_graph_scratch_bytes': G._plan_graph_scratch_bytes(case.collar),
            'binding_scratch_bytes': G._binding_scratch_bytes(native, case.collar),
            'fields_scratch_bytes': G._fields_scratch_bytes(case.collar, native.state),
            'compact_parent_scratch_bytes': G._compact_parent_scratch_bytes(case.funding, case.geometry)}
        routes = {'compact': lambda: case.bind(view), 'dict': case.bind_dict}
        for name, bind in routes.items():
            row = {}
            state['now'] = state['peak'] = 0
            binding = bind()
            row['booked_peak_bytes'] = state['peak']
            row['record_sha256'] = hashlib.sha256(binding._record).hexdigest()
            row['record_bytes'] = len(binding._record)
            del binding
            gc.collect()
            row['booked_after_release_bytes'] = state['now']
            seconds = []
            for _ in range(REPEATS):
                started = time.perf_counter()
                binding = bind()
                seconds.append(time.perf_counter()-started)
                del binding
                gc.collect()
            row['median_seconds'] = statistics.median(seconds)
            row['seconds'] = seconds
            report['routes'][name] = row
        tracemalloc.start()
        for name, bind in routes.items():
            peaks = []
            for _ in range(3):
                gc.collect()
                tracemalloc.reset_peak()
                base = tracemalloc.get_traced_memory()[0]
                binding = bind()
                peaks.append(tracemalloc.get_traced_memory()[1]-base)
                del binding
            report['routes'][name]['real_peak_bytes'] = max(peaks)
            report['routes'][name]['real_peaks'] = peaks
        tracemalloc.stop()
        with open(out, 'w', encoding='utf-8') as handle:
            json.dump(report, handle, indent=1)
        print(json.dumps({k: report['routes'][k] for k in report['routes']}, indent=1))
        # The route closures hold the compact view: release both before the
        # fixture's own zero-reservation teardown check.
        del routes, bind, view, native
        gc.collect()
    finally:
        case.tearDown()
        cls.tearDownClass()
        budget_class.reserve = original
        TGC.tearDownModule()


if __name__ == '__main__':
    main()
