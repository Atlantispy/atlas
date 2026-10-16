"""Compose the live heat issuer in memory and print a line range (read-only).

Usage: python -B compose_issuer.py [START END] [--write OUT.py]
Applies, in the bundle's order, private_heat_indexed_runtime.issuer_source,
heat_ledger_issuer_patch.issuer_source and live_spatial_patch.issuer_source to
H/private_heat_native_issuer_r12.py, then prints the SHA-256 of the result
and the requested lines (numbered). Nothing outside the optional OUT is written.
"""
import sys
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]
C = R/'compact-geometry-r1'
I = R.parent/'runtime-integration-r1'/'runtime-src'
H = R.parents[2]/'heat-repair-20261007'


def main():
    sys.path[:0] = [str(C), str(R), str(I)]
    import heat_ledger_issuer_patch as LEDGER
    import live_spatial_patch as LIVE
    import private_heat_indexed_runtime as INDEXED
    text = (H/'private_heat_native_issuer_r12.py').read_text(encoding='utf8')
    for transform in (INDEXED.issuer_source, LEDGER.issuer_source, LIVE.issuer_source):
        text = transform(text)
    print('sha256', sha256(text.encode('utf8')).hexdigest())
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if '--write' in sys.argv:
        Path(sys.argv[sys.argv.index('--write')+1]).write_text(text, encoding='utf8', newline='\n')
    if len(args) >= 2:
        lines = text.splitlines()
        for number in range(int(args[0]), min(int(args[1]), len(lines))+1):
            print(f'{number:5d}  {lines[number-1]}')


if __name__ == '__main__':
    main()
