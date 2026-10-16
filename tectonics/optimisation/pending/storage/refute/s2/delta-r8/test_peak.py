import gzip, importlib.util, random, tracemalloc
from pathlib import Path
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('lg', HERE.parents[3]/'so/s2/r8/ledger_fresh_interval.py')
LG = importlib.util.module_from_spec(spec); spec.loader.exec_module(LG)
W = HERE/'w'
noise = random.Random(7).randbytes(24 << 20)
(W/'big.json.gz').write_bytes(gzip.compress(noise, compresslevel=0, mtime=0)); (W/'unrel.bin').write_bytes(noise); del noise
for label, args in (('big gz, raw 10', (W/'big.json.gz', 10)), ('unrelated, raw 1<<30', (W/'unrel.bin', 1 << 30))):
    tracemalloc.start()
    try: LG.legacy_bytes(*args)
    except LG.LedgerRefused as e: msg = str(e)[:40]
    p = tracemalloc.get_traced_memory()[1]; tracemalloc.stop()
    print('%-22s peak %.2f MiB  (%s)' % (label, p / 2**20, msg))
