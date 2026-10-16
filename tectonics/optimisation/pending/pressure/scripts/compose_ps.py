"""Test-only composition for the pressure-stage candidates (T/ps): copy a base runtime, apply P1/P2/P3.

The base is never written. Two layouts:
  frozen:<folder>  a checkpoint composition (<folder>/src/atlas_tectonics + <folder>/helpers),
                   e.g. composed-r2; the copy keeps that layout (run it as frozen:<target>).
  test:<folder>    a test composition (<folder>/atlas_tectonics + TEST_COMPOSITION.json), e.g.
                   gg/workers6-r6; the copy keeps that layout (run it as test:<target>); the base's
                   manifest is kept as BASE_TEST_COMPOSITION.json.
Transform groups, always applied in this order whatever order they are named in:
  p2  integration_spatial_pressure.py   (ps_p2_spatial: the private _held preparation reuse)
  p1  integration_differential_pressure.py (ps_p1_loop), integration_parallel_binding.py
      (ps_p1_binding), integration_parallel_dispatch.py (ps_p1_dispatch), and the new package
      module integration_pressure_walls.py (runtime/); requires p2 (wall_set passes _held)
  p3  integration_pressure_coupling.py  (ps_p3_coupling)
  null  adds only atlas_tectonics/ps_identity_null.py (a docstring): the identity control. Every
      package source is digested into the execution identity, so this run differs from its base
      in identities only; fields that differ there are what any source change moves (D-b control).
Every transform checks its input pin. The manifest records each file's input and output
sha256, each transform module's sha256, the added module's sha256, and every .py file.
Usage: compose_ps.py <new-short-folder> <frozen:|test:base> <group>...
"""
import importlib.util
import json
import shutil
import sys
from hashlib import sha256
from pathlib import Path

PS = Path(__file__).resolve().parent.parent
GROUPS = {
    'p2': (('transforms/ps_p2_spatial.py', 'integration_spatial_pressure.py'),),
    'p1': (('transforms/ps_p1_loop.py', 'integration_differential_pressure.py'),
           ('transforms/ps_p1_binding.py', 'integration_parallel_binding.py'),
           ('transforms/ps_p1_dispatch.py', 'integration_parallel_dispatch.py')),
    'p3': (('transforms/ps_p3_coupling.py', 'integration_pressure_coupling.py'),),
    'null': (),
}
ORDER = ('p2', 'p1', 'p3', 'null')
NULL = b'"""T/ps identity control: no code. Adding it changes only the execution identity."""\n'
MODULE = 'runtime/integration_pressure_walls.py'


def _sha(data):
    return sha256(data).hexdigest()


def _load(path):
    spec = importlib.util.spec_from_file_location('ps_transform_'+path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    target, base, names = Path(sys.argv[1]).resolve(), sys.argv[2], sys.argv[3:]
    unknown = [name for name in names if name not in GROUPS]
    if unknown or not names:
        raise SystemExit('name one or more of %s (nothing copied); unknown: %s' % (ORDER, unknown))
    if 'p1' in names and 'p2' not in names:
        raise SystemExit('p1 requires p2: wall_set passes the private _held preparation')
    if target.exists():
        raise SystemExit('target exists')
    if len(str(target)) > 120:
        raise SystemExit('target path too long for the deep package files (keep it short)')
    kind, _, folder = base.partition(':')
    folder = Path(folder).resolve()
    if kind == 'frozen':
        if not ((folder/'src'/'atlas_tectonics').is_dir() and (folder/'helpers').is_dir()):
            raise SystemExit('not a src/ + helpers/ composition folder')
        target.mkdir(parents=True)
        for part in ('src', 'helpers'):
            shutil.copytree(folder/part, target/part, ignore=shutil.ignore_patterns('__pycache__'))
        package, root = target/'src'/'atlas_tectonics', target
        base_manifest = folder/'composition.json'
        manifest_name = 'PS_COMPOSITION.json'
    elif kind == 'test':
        if not ((folder/'atlas_tectonics').is_dir() and (folder/'TEST_COMPOSITION.json').is_file()):
            raise SystemExit('not a test composition folder')
        shutil.copytree(folder, target, ignore=shutil.ignore_patterns('__pycache__'))
        (target/'TEST_COMPOSITION.json').rename(target/'BASE_TEST_COMPOSITION.json')
        package, root = target/'atlas_tectonics', target
        base_manifest = folder/'TEST_COMPOSITION.json'
        manifest_name = 'TEST_COMPOSITION.json'
    else:
        raise SystemExit('base must be frozen:<folder> or test:<folder>')
    applied = []
    for group in ORDER:
        if group not in names:
            continue
        for module_path, relative in GROUPS[group]:
            module = _load(PS/module_path)
            file = package/relative
            before = file.read_bytes().decode('utf8')    # exact bytes; no newline translation
            after = module.transform(before)              # pinned input: never allow_unreviewed_input
            file.write_bytes(after.encode('utf8'))
            applied.append(dict(group=group, transform=module_path, module_sha256=_sha((PS/module_path).read_bytes()),
                                file='atlas_tectonics/'+relative, input_sha256=_sha(before.encode()),
                                output_sha256=_sha(after.encode())))
    added = None
    if 'p1' in names:
        new = package/'integration_pressure_walls.py'
        if new.exists():
            raise SystemExit('the base already has integration_pressure_walls.py')
        data = (PS/MODULE).read_bytes()
        with new.open('xb') as stream:
            stream.write(data)
        added = dict(source=MODULE, file='atlas_tectonics/integration_pressure_walls.py', sha256=_sha(data))
    if 'null' in names:
        null = package/'ps_identity_null.py'
        with null.open('xb') as stream:
            stream.write(NULL)
        added = dict(added or {}, null=dict(file='atlas_tectonics/ps_identity_null.py', sha256=_sha(NULL)))
    files = {str(p.relative_to(root)).replace('\\', '/'): _sha(p.read_bytes()) for p in sorted(root.rglob('*.py'))}
    manifest = dict(schema='atlas.private.test-composition.r1', composer='T/ps/scripts/compose_ps.py',
                    base=dict(kind=kind, folder=str(folder), manifest=base_manifest.name,
                              manifest_sha256=_sha(base_manifest.read_bytes()) if base_manifest.is_file() else None),
                    groups=[g for g in ORDER if g in names], transforms=applied, added_module=added,
                    files=files, test_only=True,
                    record_identity='numbers byte-identical; execution identity changes (D-b)')
    (root/manifest_name).write_text(json.dumps(manifest, indent=1), encoding='utf8')
    print(json.dumps(dict(target=str(target), runtime='%s:%s' % (kind, target), transforms=applied, added=added), indent=1))


if __name__ == '__main__':
    main()
