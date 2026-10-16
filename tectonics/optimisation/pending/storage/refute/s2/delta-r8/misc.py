import gzip, importlib.util, zlib
from pathlib import Path
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('lg', HERE.parents[3]/'so/s2/r8/ledger_fresh_interval.py')
LG = importlib.util.module_from_spec(spec); spec.loader.exec_module(LG)
p = HERE/'w'/'misc.bin'
g = gzip.compress(b'abc', mtime=0)
cases = {'zlib stream': zlib.compress(b'abc'), 'raw deflate': zlib.compressobj(6, zlib.DEFLATED, -15).compress(b'abc'),
         'CM=7': g[:2]+b'\x07'+g[3:], 'good': g, 'good + 0xff pad': g+b'\xff', 'good + NUL x100000': g+bytes(100000),
         'good + NUL + good + NUL': g+b'\0'+g+b'\0', 'tab pad': g+b'\t'+g, 'newline pad': g+b'\n'}
for k, d in cases.items():
    p.write_bytes(d)
    try: e = gzip.decompress(d)
    except Exception as x: e = type(x).__name__
    try: r = bytes(LG.legacy_bytes(p, 6 if k == 'good + NUL + good + NUL' else 3))
    except LG.LedgerRefused as x: r = 'Refused'
    print('%-26s gzip=%-12r legacy=%r' % (k, e, r))
