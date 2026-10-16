import random, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fuzz_stream as F
from collections import Counter
mod, spy = F.load(1 << 20)
path = F.WORK/'case2.bin'
c = Counter()
for seed in range(3000):
    rng = random.Random(seed)
    tag, data = F.case(rng)
    ok, expected = F.oracle(data)
    if not ok:
        continue
    path.write_bytes(data)
    spy['calls'], spy['limit'] = 0, 8*len(data)+50
    try:
        mod.legacy_bytes(path, len(expected))
    except mod.LedgerRefused as e:
        msg = str(e)
        c[msg.split('(')[-1][:60] if '(' in msg else msg[-40:]] += 1
print(c)
