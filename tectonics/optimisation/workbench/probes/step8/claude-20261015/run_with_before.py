"""Run one test module with chosen pre-edit copies first on the import path.

Usage: python -B run_with_before.py MODULE FILE [FILE ...]
Each FILE is copied from before-src (hash-checked against the takeover
snapshot) into a fresh folder under R/L that is placed first on sys.path, so
the module under test imports those originals instead of the current C files.
Isolates whether a current edit causes a failure. Nothing in C is touched.
"""
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]
C = R/'compact-geometry-r1'
I = R.parent/'runtime-integration-r1'/'runtime-src'


def main():
    module, files = sys.argv[1], sys.argv[2:]
    recorded = json.loads((HERE/'baseline-hashes-takeover.json').read_text(encoding='utf8'))
    (R/'L').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='before-', dir=R/'L') as directory:
        for name in files:
            raw = (HERE/'before-src'/name).read_bytes()
            if hashlib.sha256(raw).hexdigest() != recorded['compact-geometry-r1/'+name]['sha256']:
                raise SystemExit('before-src copy differs from takeover: '+name)
            (Path(directory)/name).write_bytes(raw)
        sys.path[:0] = [directory, str(C), str(R), str(I)]
        suite = unittest.defaultTestLoader.loadTestsFromName(module)
        result = unittest.TextTestRunner(verbosity=1).run(suite)
        for name in files:
            loaded = sys.modules.get(name[:-3])
            print('loaded', name, 'from', None if loaded is None else loaded.__file__)
        shutil.rmtree(Path(directory)/'__pycache__', ignore_errors=True)
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == '__main__':
    main()
