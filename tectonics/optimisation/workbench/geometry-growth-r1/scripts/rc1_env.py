"""Import the frozen RC1 runtime read-only (no file under RC1 is written).

Puts RC1's runtime-src and composed helpers first on sys.path, refuses an
already-imported atlas_tectonics, and records the source digest of every RC1
module this process loads, so an evidence file can name its exact runtime.
"""
from hashlib import sha256
import os
import sys
from pathlib import Path

R = Path(__file__).resolve().parents[2]
RC1_ROOT = R / 'composed-r1' / 'runtime-src'
HELPERS = R / 'composed-r1' / 'helpers'
# The r4 interval-2 run's runtime (geometry d3efc44d), for like-for-like timing.
R7_ROOT = R.parents[2] / 'heat-repair-20261007' / 'native-composed-r7' / 'tectonics' / 'src'
RUNTIME = 'rc1'


def install(runtime='rc1'):
    global RC1_ROOT, HELPERS, RUNTIME
    if any(k == 'atlas_tectonics' or k.startswith('atlas_tectonics.') for k in sys.modules):
        raise RuntimeError('fresh process required')
    os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
    os.environ.setdefault('OMP_NUM_THREADS', '1')
    RUNTIME = runtime
    if runtime == 'r7':
        RC1_ROOT, HELPERS = R7_ROOT, R7_ROOT
        sys.path[:0] = [str(R7_ROOT)]
    elif runtime == 'rc1':
        sys.path[:0] = [str(RC1_ROOT), str(HELPERS)]
    elif runtime.startswith('test:'):
        # A test-only composition made by compose_test_runtime.py (RC1 + transforms).
        RC1_ROOT = Path(runtime[5:]).resolve()
        if not (RC1_ROOT / 'TEST_COMPOSITION.json').is_file():
            raise ValueError('not a test composition folder')
        # A composition that carries its own helper modules (e.g. the Step 10 dry run, whose
        # Step 8 stages import newer live_*/partition_* helpers than composed-r1's) names them
        # explicitly: RC1_ENV_TEST_HELPERS="<composition folder>|<helpers folder>". Only that
        # composition gets them, ahead of composed-r1/helpers; every other runtime is unchanged.
        own = os.environ.get('RC1_ENV_TEST_HELPERS', '')
        folder, _, helpers = own.partition('|')
        if own and Path(folder).resolve() == RC1_ROOT:
            if not Path(helpers).is_dir():
                raise ValueError('RC1_ENV_TEST_HELPERS names a missing helpers folder')
            HELPERS = Path(helpers).resolve()
            sys.path[:0] = [str(RC1_ROOT), str(HELPERS), str(R / 'composed-r1' / 'helpers')]
        else:
            sys.path[:0] = [str(RC1_ROOT), str(HELPERS)]
    else:
        raise ValueError('runtime must be rc1, r7 or test:<folder>')
    import atlas_tectonics  # noqa: F401
    if not Path(atlas_tectonics.__file__).resolve().is_relative_to(RC1_ROOT):
        raise RuntimeError('atlas_tectonics did not resolve to the selected runtime')


def loaded_sources():
    """sha256 of every loaded module file under RC1 runtime-src or helpers."""
    out = {}
    for name, module in sorted(sys.modules.items()):
        path = getattr(module, '__file__', None)
        if not path:
            continue
        p = Path(path).resolve()
        for root in (RC1_ROOT, HELPERS):
            if p.is_relative_to(root) and p.suffix == '.py':
                out[str(p.relative_to(R)).replace('\\', '/')] = sha256(p.read_bytes()).hexdigest()
    return out


def package_digest():
    """One digest over every .py file of RC1 runtime-src (sorted relative paths)."""
    h = sha256()
    for p in sorted(RC1_ROOT.rglob('*.py')):
        h.update(str(p.relative_to(RC1_ROOT)).replace('\\', '/').encode() + b'\0')
        h.update(sha256(p.read_bytes()).digest())
    return h.hexdigest()
