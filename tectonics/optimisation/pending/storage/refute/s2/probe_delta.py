"""Refuter delta probe: (A) import-time route check under existing importers' sys.path; (B) ledger receipt-mismatch matrix."""
import json, os, subprocess, sys, tempfile
from pathlib import Path
T = 'C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10'
R = T+'/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1'
RUNTIME = T+'/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/runtime-integration-r1/runtime-src'
S2 = T+'/so/s2'
PY = sys.executable
# (A) candidate imported with the sys.path of test_step8_runtime/compose_live_fixture and compact-geometry-r1 tests
for label, roots in (('step8-runtime/compose path [C, RUNTIME, R->S2]', [R+'/compact-geometry-r1', RUNTIME, S2]),
                     ('composed-r2 run roots as they stand [helpers, src] + S2 first', [S2, R+'/composed-r2/helpers', R+'/composed-r2/src'])):
    code = 'import sys; sys.path[:0]=%r\ntry:\n import compact_restart_patch\n print("imported")\nexcept BaseException as e:\n print(type(e).__name__, e)' % (roots,)
    out = subprocess.run([PY, '-B', '-I', '-c', code], capture_output=True, text=True)
    print('A', label, '->', (out.stdout+out.stderr).strip()[-200:])
# (B) receipt mismatch matrix through LG.capture
sys.path[:0] = [S2, R+'/composed-r2/helpers', R+'/diagnostic-captures', R+'/composed-r2/src']
from atlas_tectonics.resources import WorkBudget
import compact_restart_patch as CRP
import ledger_fresh_interval as LG
caught = (LG.LedgerRefused, KeyError, TypeError, ValueError, OSError)
out = Path(T+'/so/refute/s2/tmp'); out.mkdir(exist_ok=True)
budget = WorkBudget(256 << 20)
with tempfile.TemporaryDirectory(dir=out) as d:
    d = Path(d)
    raw = json.dumps({'cells': [{'cell_id': str(i), 'v': i*7} for i in range(20000)]}).encode()
    (d/'a').mkdir(); (d/'b').mkdir()
    row = CRP.capture_operands(d/'a', budget=budget, check=lambda: None, bounds=raw)['bounds']
    other = CRP.capture_operands(d/'b', budget=budget, check=lambda: None, bounds=raw[:-2]+b'}}')['bounds']
    cases = {'genuine': {}, 'raw_bytes-1': {'raw_bytes': row['raw_bytes']-1}, 'raw_bytes+1': {'raw_bytes': row['raw_bytes']+1},
             'stored-1': {'stored_bytes': row['stored_bytes']-1}, 'stored+1000': {'stored_bytes': row['stored_bytes']+1000},
             'container wrong': {'container_sha256': '1'*64}, 'raw_sha wrong': {'raw_sha256': '1'*64},
             'raw_bytes True': {'raw_bytes': True}, 'stored str': {'stored_bytes': '9'}, 'container None': {'container_sha256': None},
             'other file+own container': {'container_sha256': other['container_sha256'], 'stored_bytes': other['stored_bytes'], 'path': '../b/'+other['path']},
             'raw_bytes 1<<45': {'raw_bytes': 1 << 45}, 'raw_bytes 1<<63': {'raw_bytes': 1 << 63},
             'missing stored_bytes': {'stored_bytes': KeyError}}
    for label, change in cases.items():
        operand = {k: v for k, v in dict(row, **change).items() if v is not KeyError}
        try:
            LG.capture(d/'a', operand)
            print('B', label, '-> PASSED (read ok)')
        except BaseException as e:
            print('B', label, '->', type(e).__name__, '| main catches:', isinstance(e, caught), '|', str(e)[:70])
    print('reserved', budget.reserved_bytes)
