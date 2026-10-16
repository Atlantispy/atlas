import sys, gc
from pathlib import Path
C = 'C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/compact-geometry-r1'
sys.path[:0] = ['C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/so/s9', C]
import test_private_heat_indexed_runtime as TP
TP.setUpModule()
try:
    import mesh_tables as MT
    budget = TP.WorkBudget(256 << 20)
    record = TP.FIXTURE.two_cell_record(budget)
    view = TP.FIXTURE.T.compact_fixture(record, budget)
    print('arrays type', type(view._arrays).__name__, len(view._arrays), 'segment', view._segment, 'reader source', getattr(view._reader, 'source', '-'))
    for name, a in list(view._arrays.items())[:40]:
        print(name, type(a).__name__, a.flags.writeable, type(a.base).__name__, type(getattr(a.base, 'owner', None)).__name__, a.shape, a.dtype)
    ident = view.identity()
    print('identity', ident.record_schema, ident.sha256 == view.geometry_id, ident.record_schema == MT.LEGACY)
    del view, record; gc.collect()
finally:
    TP.tearDownModule()
