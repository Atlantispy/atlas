"""Compare the live transport transform of I's source with the composed layouts.

Usage: python -B transport_source_hash.py
Prints the SHA-256 of live_spatial_patch.transport_source(I transport source)
and of each shared composition layout's integration_spatial_transport.py, so a
harness that transforms I's file directly can state whether it runs the same
bytes as the composed runtime.
"""
from hashlib import sha256
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]
C = R/'compact-geometry-r1'
I = R.parent/'runtime-integration-r1'/'runtime-src'


def main():
    sys.path[:0] = [str(C), str(R), str(I)]
    import live_spatial_patch as L
    source = (I/'atlas_tectonics'/'integration_spatial_transport.py').read_text(encoding='utf8')
    print('transform-of-I', sha256(L.transport_source(source).encode('utf8')).hexdigest())
    for layout in sorted((R/'L').glob('*/runtime-src/atlas_tectonics/integration_spatial_transport.py')):
        print(layout.parents[2].name, sha256(layout.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
