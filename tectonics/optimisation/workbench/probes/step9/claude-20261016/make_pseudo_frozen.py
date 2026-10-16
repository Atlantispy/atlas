"""Build a pseudo-frozen helpers folder from a same-call control layout (validation of heat_control_on_frozen).

Usage: python -B make_pseudo_frozen.py LAYOUT TARGET_HELPERS

Copies LAYOUT/helpers/*.py and LAYOUT/ram/*.py into the new flat TARGET_HELPERS (refusing any
name collision), and replaces private_heat_native_issuer_r13.py by its production bytes: the
layout's copy with the control's inserted r12 reference functions removed again. Those bytes must
hash to the control record's composed_r13_sha256_before_reference_insert.
"""
import json
import shutil
import sys
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]
C = R/'compact-geometry-r1'
H = R.parents[3]/'fidelity-integration-20261005'/'heat-repair-20261007'
ISSUER = 'private_heat_native_issuer_r13.py'


def main():
    layout, target = Path(sys.argv[1]).resolve(), Path(sys.argv[2])
    target.mkdir(parents=True)
    for folder in (layout/'helpers', layout/'ram'):
        for path in sorted(folder.glob('*.py')):
            if (target/path.name).exists():
                raise SystemExit('name collision between helpers and ram: '+path.name)
            shutil.copyfile(path, target/path.name)
    expected = json.loads((layout/'control.json').read_text(encoding='utf8'))['composed_r13_sha256_before_reference_insert']
    sys.path[:0] = [str(target), str(C)]
    import private_heat_indexed_runtime as P
    import step7_same_call_heat_control as CONTROL
    predecessor = P.issuer_source((H/'private_heat_native_issuer_r12.py').read_text(encoding='utf8'))
    inserted = (target/ISSUER).read_bytes().decode('utf8')
    block = CONTROL.reference_functions(predecessor)+CONTROL.MARKER
    if inserted.count(block) != 1:
        raise SystemExit('inserted reference block not found exactly once')
    production = inserted.replace(block, CONTROL.MARKER)
    digest = sha256(production.encode()).hexdigest()
    if digest != expected:
        raise SystemExit(f'restored r13 {digest} differs from the recorded {expected}')
    (target/ISSUER).write_bytes(production.encode('utf8'))
    print(json.dumps({'helpers': str(target), 'files': len(list(target.glob('*.py'))), 'r13': digest}))


if __name__ == '__main__':
    main()
