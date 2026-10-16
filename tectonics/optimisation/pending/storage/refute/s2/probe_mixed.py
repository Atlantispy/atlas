"""Refuter probe: the real case, r9 gzip receipt vs rerun capture receipt, through one ledger call."""
import json, sys, tempfile
from pathlib import Path
T = 'C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10'
R = T+'/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1'
sys.path[:0] = [T+'/so/s2', R+'/composed-r2/helpers', R+'/diagnostic-captures', R+'/composed-r2/src']
from atlas_tectonics.resources import WorkBudget
import compact_restart_patch as CRP
import ledger_fresh_interval as LG
import test_ledger_fresh_interval as TL
out = Path(T+'/so/refute/s2/tmp'); out.mkdir(exist_ok=True)
budget = WorkBudget(256 << 20)
with tempfile.TemporaryDirectory(dir=out) as d:
    runs = TL.Runs(d)
    original = runs.receipt
    def receipt(name, bounds, arrays, **keys):
        folder, record = original(name, bounds, arrays, **keys)
        if name == 'rerun':
            (folder/'preadvance-bounds.json.gz').unlink()
            raw = json.dumps(bounds, sort_keys=True).encode()
            record['preadvance_operands']['bounds'] = CRP.capture_operands(folder, budget=budget, check=lambda: None, bounds=raw)['bounds']
        return folder, record
    runs.receipt = receipt
    result = runs.run()
    print('mixed verdict', result['verdict'], 'operands', result['heat_inputs']['operands']['bounds'] if 'bounds' in result['heat_inputs']['operands'] else None)
    print('reserved after', budget.reserved_bytes)
