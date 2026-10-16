"""Write reading copies of the partition source at each transform stage.

Usage: python -B dump_partition_sources.py OUT_DIR
Writes pn.py (partition_native_patch.transform output: the exact LP.transform
input), lp.py (after live_partition_patch.transform) and lpl.py (after
transform_lifetimes), each with its SHA-256. Reading aids only; nothing is
imported or executed from them.
"""
import hashlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]
C = R/'compact-geometry-r1'
I = R.parent/'runtime-integration-r1'/'runtime-src'


def main():
    out = Path(sys.argv[1])
    out.mkdir(exist_ok=True)
    sys.path[:0] = [str(C), str(R), str(I)]
    import live_partition_patch as LP
    import partition_native_patch as PN
    source = (I/'atlas_tectonics'/'integration_differential_geometry.py').read_text(encoding='utf8')
    stages = {'pn.py': PN.transform(source)}
    stages['lp.py'] = LP.transform(stages['pn.py'])
    stages['lpl.py'] = LP.transform_lifetimes(stages['pn.py'])
    for name, text in stages.items():
        (out/name).write_text(text, encoding='utf8', newline='\n')
        print(name, hashlib.sha256(text.encode()).hexdigest(), len(text.splitlines()))


if __name__ == '__main__':
    main()
