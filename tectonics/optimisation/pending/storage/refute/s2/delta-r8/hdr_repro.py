import gzip, importlib.util, struct, zlib
from pathlib import Path
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('lg', HERE.parents[3]/'so/s2/r8/ledger_fresh_interval.py')
LG = importlib.util.module_from_spec(spec); spec.loader.exec_module(LG)
payload = b'hello world'
co = zlib.compressobj(6, zlib.DEFLATED, -15); body = co.compress(payload)+co.flush()
trailer = struct.pack('<II', zlib.crc32(payload), len(payload))
def member(flags, hcrc=None):
    h = b'\x1f\x8b\x08' + bytes([flags]) + struct.pack('<IBB', 0, 0, 3)
    if flags & 2:
        h += struct.pack('<H', (zlib.crc32(h) & 0xffff) if hcrc is None else hcrc)
    return h + body + trailer
p = HERE/'w'/'hdr.gz'
for label, data in (('FHCRC correct', member(2)), ('FHCRC wrong', member(2, 0x1234)), ('reserved flag bit 0x20', member(0x20))):
    p.write_bytes(data)
    try: g = gzip.decompress(data)
    except Exception as e: g = type(e).__name__
    try: l = bytes(LG.legacy_bytes(p, len(payload)))
    except LG.LedgerRefused as e: l = 'LedgerRefused: ' + str(e)[-60:]
    print('%-24s gzip.decompress=%r  legacy_bytes=%r' % (label, g, l))
