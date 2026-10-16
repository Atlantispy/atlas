"""Bisection d1: the 11 Step 8 STAGES alone on the reviewed (I-based) same-call control layout.

Usage: python -B stages_on_control_layout.py LAYOUT WORKDIR

LAYOUT is a prepared same-call control layout (g13l1). WORKDIR (new) receives a copy of its native
package with differential_mesh_patch applied first where the STAGES need it, then
live_memory_composition.STAGES, stage by stage on LF text. A stage whose input pin or anchor does
not apply is recorded and skipped (the W4 call is the spatial family, so the partition stage may
refuse the I text). WORKDIR/control.json keeps the layout's helper paths (including its reference
r13), so heat_control_on_frozen.py child WORKDIR OUT REFERENCE runs the control on it and
compares the arrays with the reviewed run. The layout itself is only read.
"""
import json
import shutil
import sys
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]
C = R/'compact-geometry-r1'


def main():
    layout, workdir = Path(sys.argv[1]).resolve(), Path(sys.argv[2])
    if workdir.exists():
        raise SystemExit('the work directory must not exist')
    info = json.loads((layout/'control.json').read_text(encoding='utf8'))
    native = Path(info['paths'][0])
    src = workdir/'src'
    shutil.copytree(native, src, ignore=shutil.ignore_patterns('__pycache__'))
    package = src/'atlas_tectonics'
    sys.path[:0] = [str(C), str(R/'composed-r1'/'helpers'), str(R/'composed-r1'/'runtime-src')]
    import differential_mesh_patch as DP
    import live_memory_composition as LIVE
    stages, skipped = [], []

    def apply(name, label, transform):
        path = package/name
        before = path.read_bytes().decode('utf8').replace('\r\n', '\n')
        try:
            after = transform(before)
            compile(after, name, 'exec')
        except Exception as error:  # noqa: BLE001 - a stage that does not apply is recorded
            skipped.append({'module': name, 'stage': label, 'refusal': f'{type(error).__name__}: {str(error)[:200]}'})
            return False
        path.write_bytes(after.encode('utf8'))
        stages.append({'module': name, 'stage': label, 'input_sha256': sha256(before.encode()).hexdigest(),
                       'output_sha256': sha256(after.encode()).hexdigest()})
        return True

    apply('integration_differential_mesh.py', '(established) differential_mesh_patch', DP.transform)
    refused_partition = False
    for name, label, transform in LIVE.STAGES:
        if name == 'integration_differential_geometry.py' and refused_partition:
            skipped.append({'module': name, 'stage': label, 'refusal': 'after the refused partition stage'})
            continue
        if not apply(name, label, transform) and name == 'integration_differential_geometry.py':
            refused_partition = True
    control = dict(info, paths=[str(src.resolve()), *info['paths'][1:]], bisection='d1: STAGES only on '+str(layout),
                   stages=stages, skipped=skipped)
    (workdir/'control.json').write_text(json.dumps(control, indent=1), encoding='utf8')
    print(json.dumps({'applied': [row['module']+' '+row['stage'] for row in stages], 'skipped': skipped}, indent=1))


if __name__ == '__main__':
    main()
