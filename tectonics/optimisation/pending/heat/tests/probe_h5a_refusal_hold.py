"""Probe (16 Oct, after test-h5a-r2): bytes still reserved after an empty-payload refusal, per route, before and
after dropping the exception and collecting. Tells whether r6 adds a hold or r5 has the same one."""
import gc
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_h5a_prepare_reuse as T1  # noqa: E402

old = T1.load('private_heat_functionals_kernel_r5_probe', T1.FUN5)
new = T1.load('private_heat_functionals_kernel_r6_probe', T1.FUN6)
payload = dict(cells=[], faces=[])
routes = (('r5 reconstruct', lambda b: old.reconstruct(payload, boundary_point_faces=set(), boundary_power_faces=set(),
                                                       budget=b, selected_faces=())),
          ('r6 reconstruct', lambda b: new.reconstruct(payload, boundary_point_faces=set(), boundary_power_faces=set(),
                                                       budget=b, selected_faces=(), prepared_shared=None)),
          ('r6 prepare_shared', lambda b: new.prepare_shared(payload, set(), set(), 1, budget=b)),
          ('r5 _prepare', lambda b: old._prepare(payload, set(), set(), 1, budget=b, cancelled=None)))
for name, attempt in routes:
    budget = T1.WorkBudget(1 << 34)
    kept = None
    try:
        attempt(budget)
    except ValueError as e:
        kept = e
    held = budget.statistics()
    kept = None
    gc.collect()
    after = budget.statistics()
    print('%-18s held_with_exception=%d categories=%s | after_drop_gc=%d categories=%s' % (
        name, held['reserved_bytes'], held['categories'], after['reserved_bytes'], after['categories']))
