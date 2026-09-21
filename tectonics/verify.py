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
    # -B prevents writes, not reads. Refuse pre-existing local bytecode rather
    # than authenticate source while executing a different timestamp cache.
    for folder in ('src', 'tests'):
        if next((root / folder).rglob('*.pyc'), None) is not None:
            raise ValueError('local bytecode exists; use a clean source-only checkout')
    paths = [root / 'verify.py', root / 'pyproject.toml']
    paths += sorted((root / 'cases').glob('*.json'))
    if not (root / 'cases/foundations.json').is_file():
        raise ValueError('foundation case is missing')
    paths += sorted((root / 'src').rglob('*.py'))
    paths += sorted((root / 'tests').rglob('*.py'))
    paths += sorted((root / 'tools').glob('*.py'))
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
    if sys.argv[1:] not in ([], ['--core'], ['--native'], ['--acceptance']):
        print('Usage: python -I -B tectonics/verify.py [--core | --native | --acceptance]', file=sys.stderr)
        return 2
    acceptance = sys.argv[1:] == ['--acceptance']
    if acceptance:
        import importlib.util
        if importlib.util.find_spec('psutil') is None:
            raise ImportError('Resource acceptance needs the explicit psutil acceptance extra; no automatic installation')
    core_only = sys.argv[1:] == ['--core']
    native = not core_only
    if not core_only:
        import importlib.util
        if any(importlib.util.find_spec(p) is None for p in ('scipy', 'numba', 'blosc2', 'threadpoolctl', 'shapely')):
            raise ImportError('Full verification needs scipy, numba and the storage extra; --core explicitly tests reference foundations only')
    if native:
        import importlib.util
        if importlib.util.find_spec('numba') is None:
            raise ImportError('Default transport verification requires numba==0.65.1')
    sys.dont_write_bytecode = True
    before = source_inventory(ROOT)
    sys.path.insert(0, str(ROOT / 'src'))
    import numpy as np
    import atlas_tectonics
    from atlas_tectonics import reuse
    if Path(atlas_tectonics.__file__).resolve() != ROOT / 'src/atlas_tectonics/__init__.py':
        raise ValueError('imported tectonics package is not this checkout')
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'), pattern='test_foundations.py' if core_only else 'test_*.py')
    if native:
        suite.addTests(unittest.defaultTestLoader.discover(str(ROOT / 'tests'), pattern='check_native_transport.py'))
    result = unittest.TextTestRunner(stream=sys.stderr, verbosity=2).run(suite)
    resource_record = None
    if acceptance and result.wasSuccessful() and not result.skipped:
        import subprocess
        # A separate process keeps telemetry out of unit-test timings. All child
        # profiles have their own finite watchdog and immutable source inputs.
        proc = subprocess.run([sys.executable, '-I', '-B',
            str(ROOT / 'tests/check_combined_acceptance.py')],
            capture_output=True, text=True, timeout=300)
        if proc.returncode:
            print(proc.stderr, file=sys.stderr)
            resource_record = {'status': 'FAIL_RESOURCE_ACCEPTANCE', 'returncode': proc.returncode}
        else:
            resource_record = json.loads(proc.stdout)
    after = source_inventory(ROOT)
    unchanged = before == after
    passed = (result.wasSuccessful() and result.testsRun > 0 and not result.skipped and unchanged
              and (not acceptance or (resource_record is not None and
                   resource_record.get('status') == 'PASS_BOUNDED_CURRENT_PLATFORM')))
    print(json.dumps({
        'schema': 'atlas.tectonics.foundation-verification.v23',
        'profile': 'combined-resource-acceptance' if acceptance else 'core' if core_only else ('full-native-transport' if native else 'full-memory-storage'),
        'status': 'PASS_MATHEMATICAL_TESTS_ONLY' if passed else 'FAIL_OR_INCOMPLETE',
        'tests_run': result.testsRun,
        'failures': len(result.failures), 'errors': len(result.errors),
        'failure_details': [{'test': t.id(), 'traceback': detail} for t, detail in result.failures],
        'error_details': [{'test': t.id(), 'traceback': detail} for t, detail in result.errors],
        'skip_details': [{'test': t.id(), 'reason': reason} for t, reason in result.skipped],
        'skips': len(result.skipped), 'source_unchanged_during_tests': unchanged,
        'source_sha256_before': before, 'source_sha256_after': after,
        'execution_runtime': ({'threadpoolctl': __import__('threadpoolctl').__version__,
                               'process_start_method': 'spawn'} if native else None),
        'w02_runtime': (__import__('atlas_tectonics.remapping', fromlist=['w02_native_build_info']).w02_native_build_info() if native else None),
        'material_runtime': (__import__('atlas_tectonics.materials', fromlist=['material_native_build_info']).material_native_build_info() if native else None),
        'regional_runtime': (__import__('atlas_tectonics.regional', fromlist=['regional_native_build_info']).regional_native_build_info() if native else None),
        'native_runtime': (__import__('atlas_tectonics.transport', fromlist=['native_build_info']).native_build_info() if native else None),
        'R4_status': 'IN_PROGRESS',
        'R4_complete': False,
        'convection_r4_4_scope': 'published-case definitions, independent endpoint diagnostics, immutable trajectory runner, per-run and refinement gates, combined recovery tests; passing tests does not establish mature published convection or complete R4.4 acceptance',
        'thermochemical_r4_2_scope': 'retained constant-property rectangular heat/binary composition evolution and local same-source restart; explicit R4.3 mode adds nonlinear mechanics, not full convection benchmark acceptance',
        'stokes_r4_1_scope': 'retained constant-viscosity closed free-slip 2D steady mechanics; variable-stress assembly is the separate R4.3 component, not an unmodified vector Laplacian',
        'variable_stokes_r4_3_scope': 'closed 2D rectangular symmetric-stress variable-viscosity mechanics, updated-law Picard yielding and explicit two-stage Tosi thermochemical coupling; no evolving damage or full R4.4 convection benchmark acceptance',
        'physical_closure_r3_scope': 'local Tosi/BF2023 constitutive laws, explicit material-point memory and 1D fixed-length operator; R3 alone does not establish coupled localisation or R4 completion',
        'spherical_atlas_scope': 'closed static conforming patch geometry; no spherical material evolution',
        'earth_material_scope': 'W01 4B sourced reference data and declared mixtures; no hot/high-pressure laws or W03 evolution',
        'geological_description_scope': 'W01 stage 4 plus R2 pre-partition state and bounded stage-5 point/prism/shell-sector initial sampling; no W03 evolution',
        'precursor_r2_scaling_scope': 'conservative spherical candidate index and bounded independent sampling batches; auto indexed points, measured serial cell default',
        'precursor_r2_scope': 'plate-independent immutable state; conservative initial material volumes; no physical plate-formation/rheology/global-mesh acceptance',
        'planetary_generation_scope': 'W01 3C unweighted nearest-site initial geometry; not validated plate history',
        'geometry_runtime': __import__('atlas_tectonics.geometry', fromlist=['geometry_runtime']).geometry_runtime(),
        'runtime': {'python': platform.python_version(), 'numpy': np.__version__,
                    'interpreter_launcher_is_symlink': Path(sys.executable).is_symlink(),
                    'interpreter_target_sha256': reuse._loaded_binary(reuse._interpreter_binary()),
                    'platform': platform.system(), 'machine': platform.machine(),
                    'thread_environment': {k: os.environ.get(k) for k in
                        ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS')}},
        'resource_acceptance': resource_record,
        'plate_reference_r1_scope': 'parser/metric/policy checks; complete external PB2002 verification requires explicit reference command',
        'scope': 'synthetic analytical, numerical and resource checks; platform scope is explicit',
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
