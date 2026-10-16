"""Read one REAL r9 operand with the r8 legacy_bytes (read-only) and report memory only."""
import hashlib, importlib.util, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
T = HERE.parents[3]
spec = importlib.util.spec_from_file_location('lg_real', T/'so/s2/r8/ledger_fresh_interval.py')
LG = importlib.util.module_from_spec(spec); spec.loader.exec_module(LG)
D = T/'fidelity-integration-20261005/continuation-repair-20261013/recovery-r9/heat-original-connected-20261013-r9.artifacts'
name, raw = sys.argv[1], int(sys.argv[2])
out = LG.legacy_bytes(D/('preadvance-%s.json.gz' % name), raw)
print(name, len(out), hashlib.sha256(out).hexdigest()[:16])
import psutil
mi = psutil.Process().memory_info()
print('peak_wset MiB %.0f  peak_pagefile MiB %.0f  (raw %.0f MiB)' % (mi.peak_wset/2**20, mi.peak_pagefile/2**20, raw/2**20))
