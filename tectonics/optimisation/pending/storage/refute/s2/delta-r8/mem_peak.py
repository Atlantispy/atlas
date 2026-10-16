"""tracemalloc peaks of r8 legacy_bytes (success paths); memory only, no timing."""
import gzip, importlib.util, random, tracemalloc
from pathlib import Path
HERE = Path(__file__).resolve().parent
T = HERE.parents[3]
spec = importlib.util.spec_from_file_location('lg_real', T/'so/s2/r8/ledger_fresh_interval.py')
LG = importlib.util.module_from_spec(spec); spec.loader.exec_module(LG)
W = HERE/'w'; W.mkdir(exist_ok=True)
MiB = 1 << 20

def peak(label, path, raw):
    tracemalloc.start()
    try:
        out = LG.legacy_bytes(path, raw)
        n = len(out)
        del out
        p = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    print('%-48s raw %6.1f MiB  peak %7.1f MiB  ratio %.2f' % (label, raw/MiB, p/MiB, p/raw))

for size in (16, 64):
    p = W/('zeros%d.gz' % size); p.write_bytes(gzip.compress(bytes(size*MiB), compresslevel=9, mtime=0))
    peak('%d MiB zeros, one 64KiB member, raw exact' % size, p, size*MiB)
    peak('%d MiB zeros, raw+1000' % size, p, size*MiB+1000)
noise = random.Random(3).randbytes(24*MiB)
p = W/'noise24.gz'; p.write_bytes(gzip.compress(noise, compresslevel=0, mtime=0)); del noise
peak('24 MiB stored-noise member, raw exact', p, 24*MiB)
# many small members: each member independent decompressobj (no big chunk)
p = W/'many.gz'; p.write_bytes(b''.join(gzip.compress(bytes(MiB), mtime=0) for _ in range(32)))
peak('32 members x 1 MiB zeros, raw exact', p, 32*MiB)
