"""Test-only composition of the pose width successor: copy a frozen runtime, apply (b) and/or (c).

Usage: compose_width.py <new-short-folder> frozen:<base-folder> <group>...
  b   width_pose_round: integration_wall_measures.py (b-ray), integration_exterior_mesh.py (b-quat)
  c   width_deviation_bound: integration_differential_mesh.py
Groups are applied in the order b, c whatever order they are named in. The base (<folder>/src and
<folder>/helpers) is never written; the copy keeps that layout (run it as frozen:<target>). Every
transform checks its input pin. WIDTH_COMPOSITION.json records each file's input and output sha256,
each transform module's sha256, the base manifest's sha256 and every .py file's sha256.
"""
import importlib.util
import json
import shutil
import sys
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
GROUPS = {'b': 'width_pose_round.py', 'c': 'width_deviation_bound.py'}
ORDER = ('b', 'c')


def _sha(data):
    return sha256(data).hexdigest()


def _load(path):
    spec = importlib.util.spec_from_file_location('width_transform_'+path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    target, base, names = Path(sys.argv[1]).resolve(), sys.argv[2], sys.argv[3:]
    unknown = [name for name in names if name not in GROUPS]
    if unknown:
        raise SystemExit('name one or more of %s (nothing copied); unknown: %s' % (ORDER, unknown))
    if target.exists():
        raise SystemExit('target exists')
    if len(str(target)) > 120:
        raise SystemExit('target path too long for the deep package files (keep it short)')
    kind, _, folder = base.partition(':')
    folder = Path(folder).resolve()
    if kind != 'frozen' or not ((folder/'src'/'atlas_tectonics').is_dir() and (folder/'helpers').is_dir()):
        raise SystemExit('base must be frozen:<folder> with src/atlas_tectonics and helpers/')
    target.mkdir(parents=True)
    for part in ('src', 'helpers'):
        shutil.copytree(folder/part, target/part, ignore=shutil.ignore_patterns('__pycache__'))
    package = target/'src'/'atlas_tectonics'
    applied = []
    for group in ORDER:
        if group not in names:
            continue
        module_path = HERE/GROUPS[group]
        module = _load(module_path)
        for relative, transform in module.TRANSFORMS.items():
            file = package/relative
            before = file.read_bytes().decode('utf8')    # exact bytes; no newline translation
            after = transform(before)                     # pinned input: never allow_unreviewed_input
            file.write_bytes(after.encode('utf8'))
            applied.append(dict(group=group, transform=module_path.name, module_sha256=_sha(module_path.read_bytes()),
                                file='atlas_tectonics/'+relative, input_sha256=_sha(before.encode()),
                                output_sha256=_sha(after.encode())))
    base_manifests = {p.name: _sha(p.read_bytes()) for p in sorted(folder.glob('*.json'))}
    files = {str(p.relative_to(target)).replace('\\', '/'): _sha(p.read_bytes()) for p in sorted(target.rglob('*.py'))}
    manifest = dict(schema='atlas.private.test-composition.r1', composer='ps/width/compose_width.py',
                    base=dict(kind=kind, folder=folder.name, manifests=base_manifests),
                    groups=[g for g in ORDER if g in names], transforms=applied, files=files, test_only=True,
                    record_identity='identity successor: pose-derived exact values change (design r2)')
    (target/'WIDTH_COMPOSITION.json').write_text(json.dumps(manifest, indent=1), encoding='utf8')
    print(json.dumps(dict(target=target.name, runtime='frozen:'+target.name, transforms=applied), indent=1))


if __name__ == '__main__':
    main()
