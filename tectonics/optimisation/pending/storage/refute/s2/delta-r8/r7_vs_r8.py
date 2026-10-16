import importlib.util, random, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fuzz_stream as F
def ld(name, p):
    s = importlib.util.spec_from_file_location(name, p); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
R7 = ld('r7', F.T/'so/s2/r7/ledger_fresh_interval.py'); R8 = ld('r8', F.T/'so/s2/r8/ledger_fresh_interval.py')
path = F.WORK/'c3.bin'
diff = []; n = 0
def outcome(m, raw):
    try:
        return ('ok', bytes(m.legacy_bytes(path, raw)))
    except m.LedgerRefused as e:
        s = str(e)
        return ('refused', 'exceeds' if 'exceeds' in s else 'whole' if 'whole' in s else 'changed' if 'changed' in s else s[:40])
for seed in range(3000):
    tag, data = F.case(random.Random(seed))
    path.write_bytes(data)
    ok, exp = F.oracle(data)
    for raw in ([0, 5, 10**7] + ([len(exp), len(exp)-1] if ok and len(exp) else [])):
        a, b = outcome(R7, raw), outcome(R8, raw); n += 1
        if a != b:
            diff.append((seed, tag, raw, a[0], a[1] if a[0]=='refused' else len(a[1]), b[0], b[1] if b[0]=='refused' else len(b[1])))
print('compared', n, 'differences', len(diff)); print(diff[:12])
