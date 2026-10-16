"""Build a candidate native tree: a base src/atlas_tectonics + initpar r1 transforms + the new module.

Usage: python -B -I build_runtime.py BASE_SRC OUT_SRC [MODULE]
  BASE_SRC holds atlas_tectonics/ (e.g. R/composed-r2/src). OUT_SRC must not exist.
  MODULE: the integration_initial_parallel.py to add (default: the one beside this script).
Copies every base file byte for byte, replaces the five transformed files, adds
integration_initial_parallel.py, and writes OUT_SRC/../INITPAR_MANIFEST.json (base path, transform
and module digests, input -> output digests, and the digest of every other copied file).
"""
import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TRANSFORM = HERE.parent/'transforms'/'initpar_r1.py'
MODULE = HERE/'integration_initial_parallel.py'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    base, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    module_path = Path(sys.argv[3]).resolve() if len(sys.argv) > 3 else MODULE
    if module_path.name != MODULE.name:
        raise SystemExit('module file must be named ' + MODULE.name)
    if out.exists():
        raise SystemExit('%s exists' % out)
    spec = importlib.util.spec_from_file_location('initpar_r1', TRANSFORM)
    T = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(T)
    package = base/'atlas_tectonics'
    if (package/MODULE.name).exists():
        raise SystemExit('base already holds ' + MODULE.name)
    shutil.copytree(base, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    changed = {}
    for name in T.FILES:
        before = (package/name).read_bytes()
        after = T.transform(name, before.decode('utf8')).encode('utf8')
        (out/'atlas_tectonics'/name).write_bytes(after)
        changed[name] = dict(input=digest(before), output=digest(after))
    module = module_path.read_bytes()
    (out/'atlas_tectonics'/MODULE.name).write_bytes(module)
    copied = {str(p.relative_to(out)).replace('\\', '/'): digest(p.read_bytes())
              for p in sorted(out.rglob('*')) if p.is_file()}
    manifest = dict(schema='private.ck.initpar-runtime.r1', base=str(base),
                    transform=dict(path=str(TRANSFORM), sha256=digest(TRANSFORM.read_bytes())),
                    module=dict(path=str(module_path), sha256=digest(module)),
                    changed=changed, files=copied)
    (out.parent/'INITPAR_MANIFEST.json').write_text(json.dumps(manifest, indent=1), encoding='utf8')
    for name, row in changed.items():
        print(name, row['input'][:12], '->', row['output'][:12])
    print(MODULE.name, digest(module)[:12], 'files', len(copied))


if __name__ == '__main__':
    main()
