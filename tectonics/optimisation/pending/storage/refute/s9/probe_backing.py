"""Refuter probe S9: base vs candidate metric_identity when an unscoped view's
closure-backed support store changes after the seal (no .source on the reader)."""
import sys, gc, importlib.util, pickle, copy
T = 'C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10'
C = T+'/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/compact-geometry-r1'
sys.path[:0] = [T+'/so/s9', C]
import test_private_heat_indexed_runtime as TP
TP.setUpModule()
try:
    import mesh_tables as MT
    import private_heat_indexed_runtime as NEW
    print('new from', NEW.__file__)
    spec = importlib.util.spec_from_file_location('base_runtime', T+'/so/s9/base/private_heat_indexed_runtime.py')
    BASE = importlib.util.module_from_spec(spec); spec.loader.exec_module(BASE)
    budget = TP.WorkBudget(256 << 20)
    record = TP.FIXTURE.two_cell_record(budget)
    view = TP.FIXTURE.T.compact_fixture(record, budget)
    print('scope', view.scope, 'reader', type(view._reader).__name__, 'has source', hasattr(view._reader, 'source'))
    metric = TP.M.MimeticGeometry.from_compact(view, budget=budget)
    exp = view.geometry_id
    print('base ok', BASE.metric_identity(metric) == exp, 'new ok', NEW.metric_identity(metric) == exp)
    # the reader's closure holds the backing blob dict (as compact_store.open's read_support holds store chunks)
    cells = [c.cell_contents for c in (view._reader.__closure__ or ())]
    blobs = next(c for c in cells if type(c) is dict)
    key = next(iter(blobs)); original = blobs[key]
    # 1. backing blob replaced with same-length different bytes (corruption)
    blobs[key] = bytes(len(original))
    for name, mod in (('base', BASE), ('new', NEW)):
        try:
            print('corrupt', name, 'returned', mod.metric_identity(metric) == exp)
        except Exception as e:
            print('corrupt', name, 'REFUSED', type(e).__name__, str(e)[:80])
    # 2. backing blob deleted
    del blobs[key]
    for name, mod in (('base', BASE), ('new', NEW)):
        try:
            print('deleted', name, 'returned', mod.metric_identity(metric) == exp)
        except Exception as e:
            print('deleted', name, 'REFUSED', type(e).__name__, str(e)[:80])
    blobs[key] = original
    # 3. same-process: pickle / deepcopy
    for label, fn in (('pickle', lambda: pickle.loads(pickle.dumps(view))), ('deepcopy', lambda: copy.deepcopy(view))):
        try:
            fn(); print(label, 'SUCCEEDED')
        except Exception as e:
            print(label, 'refused', type(e).__name__, str(e)[:60])
    # 4. base chain depth of every array
    depths = set()
    for a in view._arrays.values():
        d, r = 0, a.base
        while type(r) is __import__('numpy').ndarray:
            d += 1; r = r.base
        depths.add((d, type(r).__name__))
    print('base chains', depths)
    del metric, view, record, blobs, cells; gc.collect()
    print('reserved after', budget.reserved_bytes)
finally:
    TP.tearDownModule()
