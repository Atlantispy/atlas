"""Bytes copied into unused_data by r8's loop for a file of 20-byte empty members, per block size (count, not time)."""
import gzip, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fuzz_stream as F
empty = gzip.compress(b'', mtime=0)
print('empty member bytes', len(empty))
for block in (1 << 14, 1 << 16, 1 << 18):
    mod, spy = F.load(block)
    total = [0]
    class O(F.SpyObj):
        eof = property(lambda self: self._eof())
        def _eof(self):
            e = self.real.eof
            if e and not getattr(self, '_c', False):
                self._c = True
                total[0] += len(self.real.unused_data)
            return e
    class Z(F.SpyZlib):
        def decompressobj(self, wbits):
            return O(F.zlib.decompressobj(wbits=wbits), self.stats)
    mod.zlib = Z(spy)
    p = F.WORK/'quad.bin'
    n = 4*block // len(empty)
    p.write_bytes(empty*n)          # 4 blocks of members
    spy['limit'] = 10**9
    out = mod.legacy_bytes(p, 0)
    print('block %7d: members %7d  unused_data bytes copied %12d  (per block %d)' % (block, n, total[0], total[0]//4))
