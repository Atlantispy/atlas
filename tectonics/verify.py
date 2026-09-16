#!/usr/bin/env python3
"""Run only the remake's bounded mathematical tests and emit a fresh JSON record.

No installer, persistent cache, old checkpoint binding, simulation runner or
historical source import. JSON goes to stdout; test detail goes to stderr.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import unittest

ROOT = Path(__file__).resolve().parent


def source_inventory(root: Path) -> dict[str, str]:
    """Hashes are observations of local source bytes, not approval or signatures."""
    paths = [root / 'verify.py', root / 'cases/foundations.json']
    paths += sorted((root / 'src').rglob('*.py'))
    paths += sorted((root / 'tests').rglob('*.py'))
    if not (root / 'src/atlas_tectonics/__init__.py').is_file():
        raise ValueError('tectonics source package is missing')
    if not list((root / 'tests').glob('test_*.py')):
        raise ValueError('no mathematical tests found')
    result = {}
    for path in paths:
        if any(parent.is_symlink() for parent in (path, *path.parents)):
            raise ValueError('verification input must not be a symbolic link')
        if not path.is_file():
            raise ValueError('verification input missing: ' + path.name)
        result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def main() -> int:
    if len(sys.argv) != 1:
        print('Usage: python -I -B tectonics/verify.py', file=sys.stderr)
        return 2
    sys.dont_write_bytecode = True
    before = source_inventory(ROOT)
    sys.path.insert(0, str(ROOT / 'src'))
    import numpy as np
    import atlas_tectonics
    if Path(atlas_tectonics.__file__).resolve() != ROOT / 'src/atlas_tectonics/__init__.py':
        raise ValueError('imported tectonics package is not this checkout')
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'), pattern='test_*.py')
    result = unittest.TextTestRunner(stream=sys.stderr, verbosity=2).run(suite)
    after = source_inventory(ROOT)
    unchanged = before == after
    passed = (result.wasSuccessful() and result.testsRun > 0 and not result.skipped and unchanged)
    print(json.dumps({
        'schema': 'atlas.tectonics.foundation-verification.v1',
        'status': 'PASS_MATHEMATICAL_TESTS_ONLY' if passed else 'FAIL_OR_INCOMPLETE',
        'tests_run': result.testsRun,
        'failures': len(result.failures), 'errors': len(result.errors),
        'skips': len(result.skipped), 'source_unchanged_during_tests': unchanged,
        'source_sha256_before': before, 'source_sha256_after': after,
        'runtime': {'python': platform.python_version(), 'numpy': np.__version__,
                    'platform': platform.system(), 'machine': platform.machine(),
                    'thread_environment': {k: os.environ.get(k) for k in
                        ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS')}},
        'scope': 'synthetic analytical and numerical unit tests',
        'physical_validation': False, 'production_ready': False,
        'historical_checkpoint_compatibility': False,
        'note': 'Local evidence record, not a cryptographic signature or performance benchmark.'
    }, indent=2, allow_nan=False))
    return 0 if passed else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ImportError, OSError, ValueError) as exc:
        print(json.dumps({'status':'BLOCKED','error':str(exc),
              'action':'Use the declared existing development dependencies; no auto-install occurs.'}), file=sys.stderr)
        raise SystemExit(2)
