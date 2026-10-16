"""Real 1 MiB boundary cases against the UNMODIFIED r8 ledger_fresh_interval.legacy_bytes."""
import gzip, importlib.util, random, sys, tracemalloc
from pathlib import Path
HERE = Path(__file__).resolve().parent
T = HERE.parents[3]
spec = importlib.util.spec_from_file_location('lg_real', T/'so/s2/r8/ledger_fresh_interval.py')
LG = importlib.util.module_from_spec(spec); spec.loader.exec_module(LG)
W = HERE/'w'; W.mkdir(exist_ok=True)
M = 1 << 20
rb = random.Random(5).randbytes(3*M)

def stored(n, tag=0):
    return gzip.compress(rb[tag:tag+n], compresslevel=0, mtime=0)

def exact(target, tag=0):
    n = target - 18 - 5*((target+65534)//65535)
    for d in range(-40, 40):
        s = stored(n+d, tag)
        if len(s) == target:
            return s
    raise SystemExit('no exact length %d' % target)

def check(label, data, expect_ok=None):
    path = W/'rb.bin'
    path.write_bytes(data)
    try:
        want = gzip.decompress(data); gok = True
    except Exception as e:
        want = type(e).__name__; gok = False
    out = []
    for raw in ([len(want), len(want)-1] if gok else [10, 1 << 30]):
        if raw < 0: continue
        try:
            got = bytes(LG.legacy_bytes(path, raw)); res = 'ok' if got == want and raw >= len(want) else 'WRONG-BYTES'
        except LG.LedgerRefused as e:
            res = 'refused:' + ('exceeds' if 'exceeds' in str(e) else 'notwhole' if 'whole' in str(e) else 'other')
        except Exception as e:
            res = 'EXC ' + type(e).__name__
        out.append((raw if raw != len(want) else 'len', res))
    status = 'OK ' if ((gok and out[0][1] == 'ok' and (len(out) < 2 or out[1][1] == 'refused:exceeds')) or
                       (not gok and all(r.startswith('refused') for _, r in out))) else 'BAD'
    print(status, label, 'gzip:', 'ok %d' % len(want) if gok else want, out)

a = exact(M)               # member exactly one block
b = exact(M, 7)
c = stored(1000, 3)
check('member ends exactly at block end, then member', a + b)
check('member exactly block, then block of zeros, then member', a + bytes(M) + c)
check('member exactly block, then 3 blocks of zeros (end)', a + bytes(3*M))
check('member exactly block, then zeros exactly 1MiB+1 then member', a + bytes(M+1) + c)
check('1 MiB-1 member then 1 pad byte then member at boundary', exact(M-1) + b'\0' + c)
check('member +1 byte over boundary (trailer split 7/1)', exact(M+1) + c)
check('trailer split 4/4', exact(M+4)[:-4] + exact(M+4)[-4:] + c)
x = exact(M+4)
check('member ends 4 bytes after boundary, trailing zeros to 2 MiB', x + bytes(2*M - len(x)))
check('truncated second member across blocks', a + b[:-3])
check('truncated second member (1 byte of header at block 2)', a + b'\x1f')
check('second header split 1 byte | rest at boundary', exact(M-1) + c)   # c starts at boundary-1+... header split 1/9
check('trailing garbage right at boundary', a + b'GARBAGE')
check('leading zero block', bytes(M) + a)
check('2 MiB of zeros only', bytes(2*M))
check('empty', b'')
check('single zero byte', b'\0')
check('member plus one byte 1f', a + b'\x1f')
check('member plus magic only', a + bytes([0x1f, 0x8b]))
check('exact 2-member where first output hits raw exactly then second empty member', stored(5) + gzip.compress(b'', mtime=0))
# max_length edge: raw_bytes exactly equals first member output, second empty
p = W/'rb2.bin'; p.write_bytes(stored(5) + gzip.compress(b'', mtime=0))
print('exact-fit with empty trailing member', bytes(LG.legacy_bytes(p, 5)) == rb[:5])
p.write_bytes(gzip.compress(b'', mtime=0) * 3)
print('3 empty members raw=0', bytes(LG.legacy_bytes(p, 0)))
p.write_bytes(gzip.compress(b'', mtime=0) + gzip.compress(b'a', mtime=0))
try:
    LG.legacy_bytes(p, 0); print('empty+a raw=0: ACCEPTED (BAD)')
except LG.LedgerRefused as e:
    print('empty+a raw=0 refused:', str(e)[:50])
