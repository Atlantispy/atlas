import gzip, random, sys, zlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fuzz_stream as F
seeds = set()
mod, spy = F.load(1 << 20)
path = F.WORK/'case2.bin'
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
        # why
        reason = None
        try:
            d = zlib.decompressobj(wbits=31)
            d.decompress(data)
        except zlib.error as ze:
            reason = str(ze)
        seeds.add((seed, tag, reason))
print(len(seeds))
from collections import Counter
print(Counter((t, r) for _, t, r in seeds))
print(sorted(seeds)[:5])
