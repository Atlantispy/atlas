"""Read-only: why live_mesh_patch.transform_exterior refuses a given integration_exterior_mesh.py.

Usage: python -B probe_exterior_seam.py FILE [FILE ...]
For each file: SHA-256, how often the seam start line occurs in build_exterior_mesh, whether
the function body ends with the expected re-raise, and the body's last lines.
"""
import sys
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]
C = R/'compact-geometry-r1'
sys.path[:0] = [str(C), str(R/'composed-r1'/'helpers'), str(R/'composed-r1'/'runtime-src')]
START = "        encoded = json.dumps(result_record, sort_keys=True, separators=(',', ':')).encode()\n"


def main():
    import live_mesh_patch as MESH
    for name in sys.argv[1:]:
        source = Path(name).read_bytes().decode('utf8')
        body = MESH._function(source, 'build_exterior_mesh')
        print(f'{Path(name).parent.parent.name}/{Path(name).name} {sha256(source.encode()).hexdigest()[:16]}: '
              f'seam start x{body.count(START)}, ends with re-raise {body.endswith("            raise" + chr(10))}, '
              f'compact_context in body {"compact_context" in body}')
        print('  last lines:', [line for line in body.splitlines()[-4:]])


if __name__ == '__main__':
    main()
