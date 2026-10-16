"""Refuter probe for S8: edge paths of producer_accounting / validate_retained_producer (read-only on R)."""
import json, os, sys, gc
from pathlib import Path
T = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10')
R = T/'fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1'
sys.path[:0] = [str(T/'so/s8'), str(R), str(R/'compact-geometry-r1'), str(R.parent/'runtime-integration-r1'/'runtime-src')]
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from content_cache import ChargeSpec, OWNER_BYTES, LIVE_PRODUCER_BYTES
import run_prepared_restart as RUN
import reopen_prepared_restart as RO
print('RO from', RO.__file__)


def record_of(scope):
    record = {}
    record['retained_scope'] = dict(before_close=RO.retained_accounting(scope))
    record['retained_producer'] = dict(before_close=RO.producer_accounting(scope))
    scope.close()
    record['retained_scope']['after_close'] = RO.retained_accounting(scope)
    record['retained_producer']['after_close'] = RO.producer_accounting(scope)
    return json.loads(json.dumps(record, sort_keys=True, allow_nan=False))


def check(name, scope):
    rec = record_of(scope)
    for v in rec['retained_scope'].values():
        RO.validate_retained_accounting(v, pid=os.getpid())
    RO.validate_retained_producer(rec, rec['retained_scope'])
    p = rec['retained_producer']
    print(name, 'OK', {k: p['before_close'][k] for k in RO.PRODUCER_SCALARS}, p['before_close']['producer_purpose_bytes'],
          'after', p['after_close']['producer_bytes'], p['after_close']['producer_purpose_bytes'])


# 1. producer child at limit, required refusal, optional decline, retained purposes too
budget = WorkBudget(8 << 30)
scope = RUN.new_retained_scope(budget)
lim = min(LIVE_PRODUCER_BYTES, budget.max_bytes)
held = [scope.reserve(ChargeSpec('record-tables', lim - OWNER_BYTES)).commit(bytearray(1))]
try:
    scope.reserve(ChargeSpec('mesh-memory-columns', 1))
    print('no refusal?!')
except MemoryLimitError:
    pass
print('optional', scope.reserve(ChargeSpec('transport-result-arrays', 1), required=False))
held.append(scope.reserve(ChargeSpec('view', 1 << 20)).commit(bytearray(1)))
# 2. leave a pending (uncommitted) producer reservation and a released one
r = scope.reserve(ChargeSpec('transport-result-field', 0), required=False)
print('pending producer reservation when full', r)
for h in held:
    h.close()
del held
gc.collect()
check('full+refusal', scope)

# 3. run budget smaller than LIVE_PRODUCER_BYTES; run-budget refusal of a producer charge
budget = WorkBudget(64 << 20)
scope = RUN.new_retained_scope(budget)
a = scope.reserve(ChargeSpec('view', 40 << 20)).commit(bytearray(1))
try:
    scope.reserve(ChargeSpec('record-tables', 30 << 20))
except MemoryLimitError:
    print('run-budget refusal of producer charge')
a.close(); del a; gc.collect()
check('small-run', scope)

# 4. before_close with a live producer owner: close must refuse; what does the reader record hold?
budget = WorkBudget(1 << 30)
scope = RUN.new_retained_scope(budget)
live = scope.reserve(ChargeSpec('record-tables', 1 << 20)).commit(bytearray(1))
rec = {'retained_scope': dict(before_close=RO.retained_accounting(scope)),
       'retained_producer': dict(before_close=RO.producer_accounting(scope))}
try:
    scope.close()
except RuntimeError as e:
    print('close refused with live producer owner:', e)
print('after failed close, producer_accounting still works:', RO.producer_accounting(scope)['producer_bytes'])
# stats on a closed-then-reused registry? new_retained_scope on same budget while open returns the same scope
print('same scope returned:', RUN.new_retained_scope(budget) is scope)
live.close(); del live; gc.collect(); scope.close()

# 5. null field and partial field
retained = {'before_close': {'scope_id': 'x'}}
print('null accepted as absent:', RO.validate_retained_producer({'retained_producer': None}, retained))
